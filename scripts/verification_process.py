"""Retain subprocess descendants and confirm their cleanup after root exit.

Windows uses retained process handles so later cleanup never opens a reused
PID. POSIX callers must launch the root in its own session/process group.
"""

from __future__ import annotations

import ctypes
import math
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from scripts.verification_memory import _windows_snapshot

_PROC_ROOT = Path("/proc")
_DEAD_STATES = {"Z", "X", "x"}


def _unconfirmed(reason: str) -> RuntimeError:
    """Create the explicit failure consumed by the verification harness."""
    return RuntimeError(f"cleanup unconfirmed: {reason}")


class OwnedDescendants:
    """Captured live descendants whose identity survives the root's exit."""

    def __init__(
        self,
        pids: list[int],
        stop_action: Callable[[float], None],
        close_action: Callable[[], None],
    ) -> None:
        """Bind backend actions; callers normally use ``capture_descendants``."""
        self._pids = tuple(sorted(pids))
        self._stop_action = stop_action
        self._close_action = close_action
        self._closed = False
        self._confirmed = False

    @property
    def pids(self) -> list[int]:
        """Return live descendant PIDs observed at capture, excluding the root."""
        return list(self._pids)

    def stop(self, timeout_seconds: float = 20) -> None:
        """Stop surviving descendants, confirm exit, and always release resources."""
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("timeout_seconds must be finite and nonnegative")
        if self._confirmed:
            return
        if self._closed:
            raise _unconfirmed("captured resources were closed before stopping descendants")
        try:
            self._stop_action(timeout_seconds)
            self._confirmed = True
        finally:
            self.close()

    def close(self) -> None:
        """Release captured native resources; repeated calls are harmless."""
        if not self._closed:
            self._closed = True
            self._close_action()


class _WindowsProcessAPI:
    """Wrap the minimal Windows process APIs with explicit failure handling."""

    def __init__(self) -> None:
        """Load kernel32 lazily and declare handle-safe C signatures."""
        from ctypes import wintypes

        self._dword = wintypes.DWORD
        self._last_error = getattr(ctypes, "get_last_error")
        self._win_error = getattr(ctypes, "WinError")
        self._kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        self._kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel.OpenProcess.restype = wintypes.HANDLE
        self._kernel.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self._kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel.TerminateProcess.restype = wintypes.BOOL
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel.CloseHandle.restype = wintypes.BOOL

    def open_process(self, pid: int) -> int | None:
        """Retain terminate/query/synchronize access, skipping only disappeared PIDs."""
        handle = self._kernel.OpenProcess(0x00101001, False, pid)
        if handle:
            return int(handle)
        error = self._last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists.
            return None
        raise self._win_error(error)

    def active(self, handle: int) -> bool:
        """Check handle identity, distinguishing exit code 259 from a live process."""
        wait_result = self._kernel.WaitForSingleObject(handle, 0)
        if wait_result == 0:
            return False
        if wait_result != 258:  # WAIT_TIMEOUT
            raise self._win_error(self._last_error())
        exit_code = self._dword()
        if not self._kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise self._win_error(self._last_error())
        return int(exit_code.value) == 259  # STILL_ACTIVE

    def terminate(self, handle: int) -> None:
        """Terminate the captured process, tolerating a concurrent natural exit."""
        if not self._kernel.TerminateProcess(handle, 1):
            error = self._last_error()
            if self.active(handle):
                raise self._win_error(error)

    def wait(self, handle: int, timeout_seconds: float) -> bool:
        """Return whether the captured process signaled exit within the timeout."""
        milliseconds = min(math.ceil(timeout_seconds * 1000), 0xFFFFFFFE)
        result = self._kernel.WaitForSingleObject(handle, milliseconds)
        if result == 0:
            return True
        if result == 258:
            return False
        raise self._win_error(self._last_error())

    def close(self, handle: int) -> None:
        """Release a retained process handle and report failures."""
        if not self._kernel.CloseHandle(handle):
            raise self._win_error(self._last_error())


@lru_cache(maxsize=1)
def _windows_api() -> _WindowsProcessAPI:
    """Reuse configured APIs without loading DLLs at module import."""
    return _WindowsProcessAPI()


def _capture_windows(root_pid: int) -> OwnedDescendants:
    """Capture descendant handles before the root can disappear."""
    handles: dict[int, int] = {}
    api = _windows_api()

    def close_handles() -> None:
        """Close every captured handle even if one close fails."""
        errors = []
        for pid, handle in list(handles.items()):
            try:
                api.close(handle)
            except Exception as error:
                errors.append(f"PID {pid}: {error}")
            finally:
                del handles[pid]
        if errors:
            raise _unconfirmed("could not release captured handles: " + "; ".join(errors))

    try:
        current = _windows_snapshot()
        selected = {root_pid}
        while True:
            descendants = {pid for pid, (parent, _) in current.items() if parent in selected}
            if descendants.issubset(selected):
                break
            selected.update(descendants)
        for pid in sorted(selected - {root_pid}):
            handle = api.open_process(pid)
            if handle is None:
                continue
            handles[pid] = handle
            if not api.active(handle):
                api.close(handle)
                del handles[pid]
    except Exception:
        close_handles()
        raise

    def stop_handles(timeout_seconds: float) -> None:
        """Terminate and wait on retained identities, never reopening a PID."""
        deadline = time.monotonic() + timeout_seconds
        errors = []
        for pid, handle in handles.items():
            try:
                if api.active(handle):
                    api.terminate(handle)
            except Exception as error:
                errors.append(f"PID {pid}: {error}")
        for pid, handle in handles.items():
            try:
                if not api.wait(handle, max(0.0, deadline - time.monotonic())):
                    errors.append(f"PID {pid}: exit was not confirmed before timeout")
            except Exception as error:
                errors.append(f"PID {pid}: {error}")
        if errors:
            raise _unconfirmed("Windows descendant termination failed: " + "; ".join(errors))

    return OwnedDescendants(list(handles), stop_handles, close_handles)


@dataclass(frozen=True)
class _ProcessIdentity:
    """Linux identity whose start time protects against PID reuse."""

    pid: int
    group_id: int
    state: str
    start_ticks: int


def _linux_group_snapshot(group_id: int) -> dict[int, _ProcessIdentity]:
    """Read group identities, excluding no process merely because it is a zombie."""
    members = {}
    for directory in _PROC_ROOT.iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            text = (directory / "stat").read_text(encoding="utf-8")
        except (FileNotFoundError, ProcessLookupError):
            continue
        _, separator, suffix = text.rpartition(")")
        fields = suffix.split()
        if not separator or len(fields) < 20:
            raise ValueError(f"Invalid procfs process identity for PID {directory.name}")
        process_group = int(fields[2])
        if process_group == group_id:
            pid = int(directory.name)
            members[pid] = _ProcessIdentity(pid, process_group, fields[0], int(fields[19]))
    return members


def _capture_posix(root_pid: int) -> OwnedDescendants:
    """Capture an isolated process group, including descendants after root exit."""
    if root_pid == int(getattr(os, "getpgrp")()):
        raise _unconfirmed("refusing to signal the verification harness's process group")
    try:
        group_id = int(getattr(os, "getpgid")(root_pid))
    except ProcessLookupError:
        group_id = root_pid
    if group_id != root_pid:
        raise _unconfirmed("root was not launched in an isolated process group")

    if sys.platform.startswith("linux"):
        captured = _linux_group_snapshot(group_id)
        identities = {(member.pid, member.start_ticks) for member in captured.values()}
        pids = [
            member.pid
            for member in captured.values()
            if member.pid != root_pid and member.state not in _DEAD_STATES
        ]

        def stop_group(timeout_seconds: float) -> None:
            """Kill the original group and consider exited zombies already stopped."""
            deadline = time.monotonic() + timeout_seconds
            current = _linux_group_snapshot(group_id)
            live = [member for member in current.values() if member.state not in _DEAD_STATES]
            if not live:
                return
            if not any((member.pid, member.start_ticks) in identities for member in live):
                raise _unconfirmed("the captured process-group identities have changed")
            try:
                getattr(os, "killpg")(group_id, getattr(signal, "SIGKILL"))
            except ProcessLookupError:
                return
            while True:
                current = _linux_group_snapshot(group_id)
                live = [member for member in current.values() if member.state not in _DEAD_STATES]
                if not live:
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _unconfirmed(
                        "live POSIX descendants survived termination: "
                        + ", ".join(str(member.pid) for member in live)
                    )
                time.sleep(min(0.05, remaining))

        def stop_with_errors(timeout_seconds: float) -> None:
            """Give Linux permission and enumeration failures an explicit cleanup label."""
            try:
                stop_group(timeout_seconds)
            except RuntimeError:
                raise
            except Exception as error:
                raise _unconfirmed(f"POSIX process-group cleanup failed: {error}") from error

        return OwnedDescendants(pids, stop_with_errors, lambda: None)

    # Without procfs, a group probe cannot provide an honest descendant PID list.
    # Fail closed when a group exists rather than reporting an empty survivor list.
    try:
        getattr(os, "killpg")(group_id, 0)
    except ProcessLookupError:
        return OwnedDescendants([], lambda timeout: None, lambda: None)
    raise _unconfirmed("this POSIX platform cannot enumerate live process-group descendants")


def capture_descendants(root_pid: int) -> OwnedDescendants:
    """Retain live descendant identities; fail explicitly when capture is incomplete."""
    if isinstance(root_pid, bool) or root_pid <= 0:
        raise ValueError("root_pid must be a positive process ID")
    try:
        if sys.platform == "win32":
            return _capture_windows(root_pid)
        if os.name == "posix":
            return _capture_posix(root_pid)
        raise _unconfirmed(f"unsupported process-cleanup platform: {sys.platform}")
    except RuntimeError as error:
        if str(error).startswith("cleanup unconfirmed:"):
            raise
        raise _unconfirmed(str(error)) from error
    except Exception as error:
        raise _unconfirmed(f"descendant capture failed: {type(error).__name__}: {error}") from error
