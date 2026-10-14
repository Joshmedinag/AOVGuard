"""Check process-tree memory accounting independently of the host platform."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from scripts import verification_memory
from scripts.verification_memory import ProcessTreeMonitor, _linux_memory, _linux_snapshot


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_tree_includes_all_descendants_and_excludes_unrelated_processes(platform: str) -> None:
    snapshot = {10: (1, "root"), 11: (10, "child"), 12: (11, "worker"), 99: (1, "other")}
    readings = {10: (100, 300), 11: (200, 400), 12: (50, 80), 99: (9000, 9999)}
    sampled: list[int] = []

    def read_memory(pid: int) -> tuple[int, int]:
        sampled.append(pid)
        return readings[pid]

    monitor = ProcessTreeMonitor(
        10, platform=platform, snapshot=lambda: snapshot, read_memory=read_memory
    )
    monitor.sample()
    result = monitor.result()

    assert sampled == [10, 11, 12]
    assert result["available"] is True
    assert result["sample_count"] == 1
    assert result["sampled_tree_peak_rss_bytes"] == 350
    assert result["processes"] == [
        {"pid": 10, "parent_pid": 1, "image": "root", "peak_rss_bytes": 300},
        {"pid": 11, "parent_pid": 10, "image": "child", "peak_rss_bytes": 400},
        {"pid": 12, "parent_pid": 11, "image": "worker", "peak_rss_bytes": 80},
    ]
    assert "need not be simultaneous" in result["note"]
    assert "shared pages" in result["note"]
    assert "miss brief peaks" in result["note"]


def test_process_high_water_marks_are_distinct_from_sampled_tree_peak() -> None:
    readings = {10: (100, 500), 11: (200, 300)}
    monitor = ProcessTreeMonitor(
        10,
        platform="win32",
        snapshot=lambda: {10: (1, "root"), 11: (10, "child")},
        read_memory=lambda pid: readings[pid],
    )
    monitor.sample()
    readings.update({10: (400, 500), 11: (100, 600)})
    monitor.sample()
    result = monitor.result()

    assert result["sampled_tree_peak_rss_bytes"] == 500
    assert [entry["peak_rss_bytes"] for entry in result["processes"]] == [500, 600]
    assert result["sample_count"] == 2
    result["processes"][0]["peak_rss_bytes"] = 0
    assert monitor.result()["processes"][0]["peak_rss_bytes"] == 500


def test_a_process_that_exits_between_enumeration_and_read_is_tolerated() -> None:
    def read_memory(pid: int) -> tuple[int, int] | None:
        if pid == 11:
            raise ProcessLookupError("worker already exited")
        if pid == 12:
            return None
        return 100, 200

    monitor = ProcessTreeMonitor(
        10,
        platform="linux",
        snapshot=lambda: {10: (1, "root"), 11: (10, "worker"), 12: (10, "exiting")},
        read_memory=read_memory,
    )
    monitor.sample()
    result = monitor.result()

    assert result["available"] is True
    assert result["sampled_tree_peak_rss_bytes"] == 100
    assert len(result["processes"]) == 1
    assert "2 process memory reads were unavailable" in result["note"]


def test_no_valid_readings_never_report_zero_memory_as_available() -> None:
    monitor = ProcessTreeMonitor(
        10, platform="win32", snapshot=lambda: {}, read_memory=lambda pid: None
    )
    assert monitor.result()["sampled_tree_peak_rss_bytes"] is None
    monitor.sample()
    result = monitor.result()

    assert result["available"] is False
    assert result["sampled_tree_peak_rss_bytes"] is None
    assert result["processes"] == []
    assert result["sample_count"] == 1
    assert "No valid process memory sample" in result["note"]


@pytest.mark.parametrize("platform", ["darwin", "freebsd14", "unsupported"])
def test_unsupported_platforms_report_unavailable_without_invoking_providers(platform: str) -> None:
    def forbidden_snapshot() -> dict[int, tuple[int, str]]:
        raise AssertionError("unsupported platform should not call its provider")

    monitor = ProcessTreeMonitor(10, platform=platform, snapshot=forbidden_snapshot)
    monitor.sample()
    result = monitor.result()

    assert result["available"] is False
    assert result["measurement"] == "unavailable"
    assert result["sampled_tree_peak_rss_bytes"] is None
    assert "Unsupported memory-monitoring platform" in result["note"]


def test_global_enumeration_errors_are_explicit_and_can_recover() -> None:
    failures = [True]

    def snapshot() -> dict[int, tuple[int, str]]:
        if failures[0]:
            raise OSError("snapshot could not be opened")
        return {10: (1, "root")}

    monitor = ProcessTreeMonitor(
        10, platform="win32", snapshot=snapshot, read_memory=lambda pid: (100, 200)
    )
    monitor.sample()
    failed = monitor.result()
    assert failed["available"] is False
    assert failed["sampled_tree_peak_rss_bytes"] is None
    assert "Process enumeration failed: OSError" in failed["note"]

    failures[0] = False
    monitor.sample()
    recovered = monitor.result()
    assert recovered["available"] is True
    assert recovered["sampled_tree_peak_rss_bytes"] == 100
    assert recovered["sample_count"] == 2
    assert "Process enumeration failed" in recovered["note"]


def test_windows_backend_loading_is_lazy_and_failures_are_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def unavailable_backend() -> verification_memory._WindowsBackend:
        calls.append("load")
        raise OSError("native memory API is unavailable")

    monkeypatch.setattr(verification_memory, "_windows_backend", unavailable_backend)
    monitor = ProcessTreeMonitor(10, platform="win32")
    assert calls == []
    assert monitor.result()["sampled_tree_peak_rss_bytes"] is None

    monitor.sample()
    result = monitor.result()
    assert calls == ["load"]
    assert result["available"] is False
    assert result["sampled_tree_peak_rss_bytes"] is None
    assert "native memory API is unavailable" in result["note"]


def test_access_denied_is_recorded_without_claiming_a_valid_sample() -> None:
    def denied_memory(pid: int) -> tuple[int, int]:
        raise PermissionError("process memory access denied")

    monitor = ProcessTreeMonitor(
        10, platform="linux", snapshot=lambda: {10: (1, "root")}, read_memory=denied_memory
    )
    monitor.sample()
    result = monitor.result()

    assert result["available"] is False
    assert result["sampled_tree_peak_rss_bytes"] is None
    assert "Memory read failed: PermissionError" in result["note"]


@pytest.mark.parametrize("reading", [(-1, 100), (100, 99)])
def test_invalid_memory_counters_are_explicitly_unavailable(reading: tuple[int, int]) -> None:
    monitor = ProcessTreeMonitor(
        10, platform="linux", snapshot=lambda: {}, read_memory=lambda pid: reading
    )
    monitor.sample()
    result = monitor.result()

    assert result["available"] is False
    assert result["sampled_tree_peak_rss_bytes"] is None
    assert "Invalid process RSS" in result["note"]


def _write_status(
    proc_root: Path,
    pid: int,
    parent: int,
    image: str,
    rss: str = "12 kB",
    peak: str = "18 kB",
) -> None:
    directory = proc_root / str(pid)
    directory.mkdir()
    (directory / "status").write_text(
        f"Name:\t{image}\nPPid:\t{parent}\nVmRSS:\t{rss}\nVmHWM:\t{peak}\n",
        encoding="utf-8",
    )


def test_linux_procfs_fixture_measures_bytes_and_ignores_vanished_entries(tmp_path: Path) -> None:
    _write_status(tmp_path, 10, 1, "root")
    _write_status(tmp_path, 11, 10, "child", rss="6 kB", peak="9 kB")
    _write_status(tmp_path, 99, 1, "unrelated", rss="999 kB", peak="999 kB")
    (tmp_path / "12").mkdir()
    (tmp_path / "uptime").write_text("1234", encoding="utf-8")

    assert _linux_snapshot(tmp_path) == {10: (1, "root"), 11: (10, "child"), 99: (1, "unrelated")}
    assert _linux_memory(10, tmp_path) == (12 * 1024, 18 * 1024)
    monitor = ProcessTreeMonitor(10, platform="linux", proc_root=tmp_path)
    monitor.sample()
    result = monitor.result()

    assert result["available"] is True
    assert result["sampled_tree_peak_rss_bytes"] == 18 * 1024
    assert [entry["peak_rss_bytes"] for entry in result["processes"]] == [18 * 1024, 9 * 1024]
    assert "VmRSS" in result["measurement"]
    assert "VmHWM" in result["measurement"]


@pytest.mark.parametrize("rss", ["12 MB", "missing", "-12 kB"])
def test_linux_invalid_status_fields_do_not_produce_a_zero_measurement(
    tmp_path: Path, rss: str
) -> None:
    _write_status(tmp_path, 10, 1, "root", rss=rss)
    monitor = ProcessTreeMonitor(10, platform="linux", proc_root=tmp_path)
    monitor.sample()
    result = monitor.result()

    assert result["available"] is False
    assert result["sampled_tree_peak_rss_bytes"] is None
    assert "Memory read failed" in result["note"]


def test_linux_missing_procfs_is_a_global_limitation(tmp_path: Path) -> None:
    monitor = ProcessTreeMonitor(10, platform="linux", proc_root=tmp_path / "missing")
    monitor.sample()
    result = monitor.result()

    assert result["available"] is False
    assert result["sampled_tree_peak_rss_bytes"] is None
    assert "Process enumeration failed" in result["note"]


def test_linux_status_without_vm_counters_has_no_valid_memory_sample(tmp_path: Path) -> None:
    directory = tmp_path / "10"
    directory.mkdir()
    (directory / "status").write_text("Name:\troot\nPPid:\t1\n", encoding="utf-8")

    assert _linux_memory(10, tmp_path) is None
    monitor = ProcessTreeMonitor(10, platform="linux", proc_root=tmp_path)
    monitor.sample()
    result = monitor.result()

    assert result["available"] is False
    assert result["sampled_tree_peak_rss_bytes"] is None


@pytest.mark.skipif(sys.platform not in {"win32", "linux"}, reason="native backend unavailable")
def test_native_backend_can_measure_the_current_process() -> None:
    monitor = ProcessTreeMonitor(os.getpid())
    monitor.sample()
    result = monitor.result()

    assert result["available"] is True, result["note"]
    assert result["sampled_tree_peak_rss_bytes"] > 0
    root = next(process for process in result["processes"] if process["pid"] == os.getpid())
    assert root["peak_rss_bytes"] > 0
    assert root["image"]


@pytest.mark.parametrize("pid", [-1, 0, True])
def test_invalid_root_pids_are_rejected(pid: int) -> None:
    with pytest.raises(ValueError, match="positive process ID"):
        ProcessTreeMonitor(pid)
