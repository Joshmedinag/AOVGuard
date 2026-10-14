"""Verify descendant cleanup even when the root subprocess has already exited."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import verification_process
from scripts.verification_process import OwnedDescendants, capture_descendants


class FakeWindowsAPI:
    def __init__(self) -> None:
        self.opened: list[int] = []
        self.terminated: list[int] = []
        self.closed: list[int] = []
        self.liveness = {111: True, 112: True}
        self.open_error: int | None = None
        self.termination_error: int | None = None
        self.wait_success = True

    def open_process(self, pid: int) -> int | None:
        self.opened.append(pid)
        if pid == self.open_error:
            raise PermissionError("process handle access denied")
        return pid + 100

    def active(self, handle: int) -> bool:
        return self.liveness.get(handle, False)

    def terminate(self, handle: int) -> None:
        self.terminated.append(handle)
        if handle == self.termination_error:
            raise PermissionError("process termination access denied")
        self.liveness[handle] = False

    def wait(self, handle: int, timeout_seconds: float) -> bool:
        return self.wait_success and not self.active(handle)

    def close(self, handle: int) -> None:
        self.closed.append(handle)


class DeniedWindowsKernel:
    def __init__(
        self,
        *,
        probe_handle: int | None = 211,
        wait_result: int = 0,
        close_success: bool = True,
    ) -> None:
        self.probe_handle = probe_handle
        self.wait_result = wait_result
        self.close_success = close_success
        self.opened: list[tuple[int, int]] = []
        self.waited: list[tuple[int, int]] = []
        self.closed: list[int] = []

    def OpenProcess(self, access: int, inherit_handle: bool, pid: int) -> int | None:
        self.opened.append((access, pid))
        return self.probe_handle if access == 0x00101000 else None

    def WaitForSingleObject(self, handle: int, milliseconds: int) -> int:
        self.waited.append((handle, milliseconds))
        return self.wait_result

    def CloseHandle(self, handle: int) -> bool:
        self.closed.append(handle)
        return self.close_success


def _mock_denied_windows_capture(
    monkeypatch: pytest.MonkeyPatch, kernel: DeniedWindowsKernel
) -> None:
    api = object.__new__(verification_process._WindowsProcessAPI)
    api._kernel = kernel
    api._last_error = lambda: 5
    api._win_error = lambda code: PermissionError(code, "Access is denied")
    monkeypatch.setattr(verification_process.sys, "platform", "win32")
    monkeypatch.setattr(verification_process, "_windows_api", lambda: api)
    monkeypatch.setattr(
        verification_process,
        "_windows_snapshot",
        lambda: {10: (1, "root"), 11: (10, "exiting-child")},
    )


def test_windows_access_denied_skips_only_a_handle_that_confirms_process_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = DeniedWindowsKernel(wait_result=0)
    _mock_denied_windows_capture(monkeypatch, kernel)

    captured = capture_descendants(10)
    assert captured.pids == []
    captured.stop()
    assert kernel.opened == [(0x00101001, 11), (0x00101000, 11)]
    assert kernel.waited == [(211, 0)]
    assert kernel.closed == [211]


def test_windows_access_denied_on_a_live_process_still_fails_cleanup_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = DeniedWindowsKernel(wait_result=258)
    _mock_denied_windows_capture(monkeypatch, kernel)

    with pytest.raises(RuntimeError, match="cleanup unconfirmed.*Access is denied"):
        capture_descendants(10)
    assert kernel.waited == [(211, 0)]
    assert kernel.closed == [211]


def test_windows_query_access_denied_still_fails_cleanup_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = DeniedWindowsKernel(probe_handle=None)
    _mock_denied_windows_capture(monkeypatch, kernel)

    with pytest.raises(RuntimeError, match="cleanup unconfirmed.*Access is denied"):
        capture_descendants(10)
    assert kernel.opened == [(0x00101001, 11), (0x00101000, 11)]
    assert kernel.waited == []
    assert kernel.closed == []


@pytest.mark.parametrize("wait_result,close_success", [(0xFFFFFFFF, True), (0, False)])
def test_windows_unconfirmed_probe_or_handle_close_cannot_be_reported_as_clean(
    monkeypatch: pytest.MonkeyPatch, wait_result: int, close_success: bool
) -> None:
    kernel = DeniedWindowsKernel(wait_result=wait_result, close_success=close_success)
    _mock_denied_windows_capture(monkeypatch, kernel)

    with pytest.raises(RuntimeError, match="cleanup unconfirmed.*Access is denied"):
        capture_descendants(10)
    assert kernel.closed == [211]


def _mock_windows(monkeypatch: pytest.MonkeyPatch, api: FakeWindowsAPI) -> None:
    monkeypatch.setattr(verification_process.sys, "platform", "win32")
    monkeypatch.setattr(verification_process, "_windows_api", lambda: api)
    monkeypatch.setattr(
        verification_process,
        "_windows_snapshot",
        lambda: {10: (1, "root"), 11: (10, "child"), 12: (11, "worker"), 99: (1, "other")},
    )


def test_windows_retains_handles_and_stops_survivors_after_root_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeWindowsAPI()
    _mock_windows(monkeypatch, api)
    captured = capture_descendants(10)
    assert captured.pids == [11, 12]
    assert api.opened == [11, 12]

    # The root and the original snapshot can disappear; stop uses retained handles.
    monkeypatch.setattr(verification_process, "_windows_snapshot", lambda: {})
    captured.stop(timeout_seconds=1)
    captured.close()
    captured.stop()

    assert api.opened == [11, 12]
    assert api.terminated == [111, 112]
    assert api.closed == [111, 112]


def test_windows_skips_descendants_that_have_already_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeWindowsAPI()
    api.liveness[112] = False
    _mock_windows(monkeypatch, api)
    captured = capture_descendants(10)

    assert captured.pids == [11]
    assert api.closed == [112]
    captured.stop()
    assert api.terminated == [111]
    assert api.closed == [112, 111]


def test_windows_capture_access_errors_release_prior_handles_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeWindowsAPI()
    api.open_error = 12
    _mock_windows(monkeypatch, api)

    with pytest.raises(RuntimeError, match="cleanup unconfirmed.*access denied"):
        capture_descendants(10)
    assert api.closed == [111]


def test_windows_stopping_one_descendant_failure_does_not_skip_other_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeWindowsAPI()
    api.termination_error = 111
    _mock_windows(monkeypatch, api)
    captured = capture_descendants(10)

    with pytest.raises(RuntimeError, match="cleanup unconfirmed.*termination failed"):
        captured.stop(timeout_seconds=0)
    assert api.terminated == [111, 112]
    assert api.closed == [111, 112]
    captured.close()
    assert api.closed == [111, 112]


def test_windows_wait_timeout_is_not_a_false_success(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeWindowsAPI()
    api.wait_success = False
    _mock_windows(monkeypatch, api)
    captured = capture_descendants(10)

    with pytest.raises(RuntimeError, match="exit was not confirmed before timeout"):
        captured.stop(timeout_seconds=0)
    assert api.closed == [111, 112]


def _identity(pid: int, state: str = "S", start: int = 1) -> verification_process._ProcessIdentity:
    return verification_process._ProcessIdentity(pid, 10, state, start)


def _mock_linux_group(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    monkeypatch.setattr(verification_process.sys, "platform", "linux")
    monkeypatch.setattr(verification_process.os, "name", "posix")
    monkeypatch.setattr(verification_process.os, "getpgrp", lambda: 1, raising=False)
    monkeypatch.setattr(verification_process.os, "getpgid", lambda pid: 10, raising=False)
    monkeypatch.setattr(verification_process.signal, "SIGKILL", 9, raising=False)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        verification_process.os,
        "killpg",
        lambda group, sig: signals.append((group, sig)),
        raising=False,
    )
    return signals


def test_linux_zombies_are_excluded_from_pids_and_confirmed_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals = _mock_linux_group(monkeypatch)
    snapshots = iter(
        [
            {10: _identity(10), 11: _identity(11), 12: _identity(12, "Z")},
            {11: _identity(11)},
            {11: _identity(11, "Z"), 12: _identity(12, "Z")},
        ]
    )
    monkeypatch.setattr(
        verification_process, "_linux_group_snapshot", lambda group: next(snapshots)
    )
    captured = capture_descendants(10)

    assert captured.pids == [11]
    captured.stop(timeout_seconds=0)
    assert signals == [(10, 9)]


def test_linux_reused_process_group_identity_is_not_signaled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals = _mock_linux_group(monkeypatch)
    snapshots = iter([{10: _identity(10), 11: _identity(11)}, {11: _identity(11, start=99)}])
    monkeypatch.setattr(
        verification_process, "_linux_group_snapshot", lambda group: next(snapshots)
    )
    captured = capture_descendants(10)

    with pytest.raises(RuntimeError, match="captured process-group identities have changed"):
        captured.stop()
    assert signals == []


def test_linux_live_survivors_at_timeout_are_an_explicit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_linux_group(monkeypatch)
    monkeypatch.setattr(
        verification_process, "_linux_group_snapshot", lambda group: {11: _identity(11)}
    )
    captured = capture_descendants(10)

    with pytest.raises(RuntimeError, match="live POSIX descendants survived termination: 11"):
        captured.stop(timeout_seconds=0)


def test_posix_refuses_the_harness_group_and_nonisolated_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_linux_group(monkeypatch)
    with pytest.raises(RuntimeError, match="verification harness's process group"):
        capture_descendants(1)

    monkeypatch.setattr(verification_process.os, "getpgid", lambda pid: 99)
    with pytest.raises(RuntimeError, match="isolated process group"):
        capture_descendants(10)


def test_linux_can_capture_survivors_after_root_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_linux_group(monkeypatch)

    def exited_root(pid: int) -> int:
        raise ProcessLookupError("parent exited")

    monkeypatch.setattr(verification_process.os, "getpgid", exited_root)
    monkeypatch.setattr(
        verification_process, "_linux_group_snapshot", lambda group: {11: _identity(11)}
    )
    captured = capture_descendants(10)
    assert captured.pids == [11]
    captured.close()


def test_other_posix_platforms_fail_closed_when_a_live_group_cannot_be_enumerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_linux_group(monkeypatch)
    monkeypatch.setattr(verification_process.sys, "platform", "darwin")

    with pytest.raises(RuntimeError, match="cannot enumerate live process-group descendants"):
        capture_descendants(10)


def test_closed_capture_cannot_claim_cleanup_and_pids_are_returned_as_a_copy() -> None:
    captured = OwnedDescendants([11], lambda timeout: None, lambda: None)
    pids = captured.pids
    pids.clear()
    assert captured.pids == [11]
    captured.close()
    captured.close()
    with pytest.raises(RuntimeError, match="closed before stopping descendants"):
        captured.stop()


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan")])
def test_invalid_stop_timeouts_are_rejected(timeout: float) -> None:
    captured = OwnedDescendants([], lambda timeout: None, lambda: None)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        captured.stop(timeout_seconds=timeout)
    captured.close()


def test_linux_procfs_parser_handles_parentheses_in_names_and_preserves_zombies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verification_process, "_PROC_ROOT", tmp_path)
    for pid, group, state in [(10, 10, "S"), (11, 10, "Z"), (99, 99, "S")]:
        directory = tmp_path / str(pid)
        directory.mkdir()
        fields = [state, "1", str(group)] + ["0"] * 16 + ["123"]
        (directory / "stat").write_text(
            f"{pid} (worker (name)) " + " ".join(fields), encoding="utf-8"
        )
    (tmp_path / "12").mkdir()
    snapshot = verification_process._linux_group_snapshot(10)

    assert snapshot == {10: _identity(10, start=123), 11: _identity(11, "Z", 123)}


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux process groups and procfs")
def test_posix_orphan_child_is_stopped_after_parent_handles_interrupt_and_exits() -> None:
    child_code = "import signal,time; signal.signal(signal.SIGINT,signal.SIG_IGN); print('ready',flush=True); time.sleep(60)"
    parent_code = (
        "import signal,subprocess,sys,time; "
        "signal.signal(signal.SIGINT,lambda *_: sys.exit(0)); "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}],stdout=subprocess.PIPE,text=True); "
        "child.stdout.readline(); print(child.pid,flush=True); time.sleep(60)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    captured: OwnedDescendants | None = None
    try:
        assert parent.stdout is not None
        child_pid = int(parent.stdout.readline())
        captured = capture_descendants(parent.pid)
        assert child_pid in captured.pids
        getattr(os, "killpg")(parent.pid, signal.SIGINT)
        assert parent.wait(timeout=5) == 0

        captured.stop(timeout_seconds=5)
        remaining = verification_process._linux_group_snapshot(parent.pid)
        assert all(member.state in {"Z", "X", "x"} for member in remaining.values())
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if captured is not None:
            captured.close()
        try:
            getattr(os, "killpg")(parent.pid, getattr(signal, "SIGKILL"))
        except ProcessLookupError:
            pass
        if parent.stdout is not None:
            parent.stdout.close()


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows handles")
def test_windows_native_handles_can_stop_a_real_owned_child() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    captured: OwnedDescendants | None = None
    try:
        captured = capture_descendants(os.getpid())
        assert child.pid in captured.pids
        captured.stop(timeout_seconds=5)
        assert child.wait(timeout=5) != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if captured is not None:
            captured.close()
