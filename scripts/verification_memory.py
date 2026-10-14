"""Sample real process-tree RSS without adding application dependencies.

The caller controls cadence (normally 0.1 seconds) and calls ``sample`` while
its subprocess runs. Importing this module never loads Windows DLLs.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

ProcessSnapshot = dict[int, tuple[int, str]]
SnapshotProvider = Callable[[], ProcessSnapshot]
MemoryReader = Callable[[int], tuple[int, int] | None]

_SAMPLING_NOTE = (
    "Per-process high-water marks need not be simultaneous. The tree peak is the "
    "largest sum of RSS readings in one sampling pass; readings are sequential, "
    "sampling can miss brief peaks, and shared pages may be counted more than once. "
    "This is not total machine RAM consumption."
)


class _WindowsBackend:
    """Load and configure the native Windows APIs only when first sampled."""

    def __init__(self) -> None:
        """Prepare Toolhelp process enumeration and working-set counters."""
        from ctypes import wintypes

        class ProcessEntry(ctypes.Structure):
            """Layout of the native PROCESSENTRY32W structure."""

            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        class MemoryCounters(ctypes.Structure):
            """Layout of the native PROCESS_MEMORY_COUNTERS structure."""

            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        self._process_entry = ProcessEntry
        self._memory_counters = MemoryCounters
        self._last_error = getattr(ctypes, "get_last_error")
        self._win_error = getattr(ctypes, "WinError")
        self._kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        self._psapi = getattr(ctypes, "WinDLL")("psapi", use_last_error=True)
        self._kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self._kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        self._kernel.Process32FirstW.restype = wintypes.BOOL
        self._kernel.Process32NextW.argtypes = self._kernel.Process32FirstW.argtypes
        self._kernel.Process32NextW.restype = wintypes.BOOL
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel.CloseHandle.restype = wintypes.BOOL
        self._kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel.OpenProcess.restype = wintypes.HANDLE
        self._psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(MemoryCounters),
            wintypes.DWORD,
        ]
        self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    def snapshot(self) -> ProcessSnapshot:
        """Enumerate process IDs, parent IDs, and executable names."""
        handle = self._kernel.CreateToolhelp32Snapshot(0x00000002, 0)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise self._win_error(self._last_error())
        entries: ProcessSnapshot = {}
        try:
            entry = self._process_entry()
            entry.dwSize = ctypes.sizeof(entry)
            valid = self._kernel.Process32FirstW(handle, ctypes.byref(entry))
            while valid:
                entries[int(entry.th32ProcessID)] = (
                    int(entry.th32ParentProcessID),
                    str(entry.szExeFile),
                )
                valid = self._kernel.Process32NextW(handle, ctypes.byref(entry))
            error = self._last_error()
            if error != 18:  # ERROR_NO_MORE_FILES is the normal end of enumeration.
                raise self._win_error(error)
        finally:
            self._kernel.CloseHandle(handle)
        return entries

    def memory(self, pid: int) -> tuple[int, int] | None:
        """Read current and lifetime-peak working-set bytes for a live process."""
        handle = self._kernel.OpenProcess(0x1010, False, pid)
        if not handle:
            return None
        try:
            counters = self._memory_counters()
            counters.cb = ctypes.sizeof(counters)
            if not self._psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)
        finally:
            self._kernel.CloseHandle(handle)


@lru_cache(maxsize=1)
def _windows_backend() -> _WindowsBackend:
    """Reuse configured native functions without eager DLL loading."""
    return _WindowsBackend()


def _windows_snapshot() -> ProcessSnapshot:
    """Return a Windows process snapshot, loading DLLs lazily."""
    return _windows_backend().snapshot()


def _windows_memory(pid: int) -> tuple[int, int] | None:
    """Return Windows current RSS and process high-water RSS in bytes."""
    return _windows_backend().memory(pid)


def _linux_status(pid: int, proc_root: Path) -> dict[str, str]:
    """Parse one procfs status file without requiring a Linux host."""
    fields = {}
    for line in (proc_root / str(pid) / "status").read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key] = value.strip()
    return fields


def _linux_snapshot(proc_root: Path) -> ProcessSnapshot:
    """Enumerate procfs processes, tolerating entries that disappear mid-read."""
    processes: ProcessSnapshot = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdecimal():
            continue
        pid = int(entry.name)
        try:
            status = _linux_status(pid, proc_root)
            processes[pid] = (int(status["PPid"]), status.get("Name", ""))
        except (OSError, ValueError, KeyError):
            continue
    return processes


def _linux_memory(pid: int, proc_root: Path) -> tuple[int, int] | None:
    """Read VmRSS and VmHWM from procfs and convert kB to bytes."""
    status = _linux_status(pid, proc_root)
    if "VmRSS" not in status or "VmHWM" not in status:
        return None

    def bytes_from_kib(value: str) -> int:
        """Validate procfs units so invalid fields cannot become zero RSS."""
        fields = value.split()
        if len(fields) != 2 or fields[1] != "kB":
            raise ValueError(f"Unexpected procfs memory field: {value!r}")
        return int(fields[0]) * 1024

    return bytes_from_kib(status["VmRSS"]), bytes_from_kib(status["VmHWM"])


class ProcessTreeMonitor:
    """Accumulate observed RSS and per-process peaks for a subprocess tree.

    ``snapshot`` and ``read_memory`` can be supplied for deterministic tests on
    either host OS. ``proc_root`` supports a procfs fixture. ``sample_count``
    counts attempted passes; ``available`` requires a valid memory reading.
    """

    def __init__(
        self,
        root_pid: int,
        *,
        platform: str | None = None,
        snapshot: SnapshotProvider | None = None,
        read_memory: MemoryReader | None = None,
        proc_root: Path = Path("/proc"),
    ) -> None:
        """Select a backend without reading memory or loading native DLLs."""
        if isinstance(root_pid, bool) or root_pid <= 0:
            raise ValueError("root_pid must be a positive process ID")
        self._root_pid = root_pid
        self._sample_count = 0
        self._valid_sample_count = 0
        self._tree_peak: int | None = None
        self._processes: dict[int, dict[str, Any]] = {}
        self._limitations: set[str] = set()
        self._unavailable_reads = 0
        selected_platform = sys.platform if platform is None else platform
        self._snapshot: SnapshotProvider | None
        self._read_memory: MemoryReader | None
        if selected_platform == "win32":
            self._snapshot = snapshot or _windows_snapshot
            self._read_memory = read_memory or _windows_memory
            self._measurement = (
                "Windows GetProcessMemoryInfo PeakWorkingSetSize per process; "
                "sampled sum of WorkingSetSize for the root and its descendants"
            )
        elif selected_platform.startswith("linux"):
            self._snapshot = snapshot or (lambda: _linux_snapshot(proc_root))
            self._read_memory = read_memory or (lambda pid: _linux_memory(pid, proc_root))
            self._measurement = (
                "Linux /proc VmHWM per process; sampled sum of VmRSS "
                "for the root and its descendants"
            )
        else:
            self._snapshot = None
            self._read_memory = None
            self._measurement = "unavailable"
            self._limitations.add(f"Unsupported memory-monitoring platform: {selected_platform}.")

    def sample(self) -> None:
        """Record one sampling pass; exited or inaccessible processes are skipped."""
        self._sample_count += 1
        if self._snapshot is None or self._read_memory is None:
            return
        try:
            current = self._snapshot()
        except Exception as error:
            # Monitoring must not interrupt the verification subprocess.
            self._limitations.add(f"Process enumeration failed: {type(error).__name__}: {error}")
            return

        selected = {self._root_pid}
        while True:
            descendants = {pid for pid, (parent, _) in current.items() if parent in selected}
            if descendants.issubset(selected):
                break
            selected.update(descendants)

        total_rss = 0
        valid_readings = 0
        for pid in sorted(selected):
            try:
                values = self._read_memory(pid)
                if values is None:
                    self._unavailable_reads += 1
                    continue
                rss, high_water = values
                if rss < 0 or high_water < rss:
                    raise ValueError("Invalid process RSS or high-water memory counters")
            except Exception as error:
                self._unavailable_reads += 1
                if not isinstance(error, (FileNotFoundError, ProcessLookupError)):
                    self._limitations.add(f"Memory read failed: {type(error).__name__}: {error}")
                continue

            total_rss += rss
            valid_readings += 1
            parent, image = current.get(pid, (None, ""))
            record = self._processes.setdefault(
                pid,
                {"pid": pid, "parent_pid": parent, "image": image, "peak_rss_bytes": high_water},
            )
            record["peak_rss_bytes"] = max(record["peak_rss_bytes"], high_water)
            if pid in current:
                record["parent_pid"] = parent
                record["image"] = image

        if valid_readings:
            self._valid_sample_count += 1
            self._tree_peak = max(self._tree_peak or 0, total_rss)

    def result(self) -> dict[str, Any]:
        """Return JSON-ready measurements and explicit sampling limitations."""
        notes = [_SAMPLING_NOTE]
        if not self._valid_sample_count:
            notes.append("No valid process memory sample was collected; memory is unavailable.")
        if self._unavailable_reads:
            notes.append(
                f"{self._unavailable_reads} process memory reads were unavailable; "
                "processes may have exited or access may have been denied."
            )
        notes.extend(sorted(self._limitations))
        return {
            "available": self._valid_sample_count > 0,
            "measurement": self._measurement,
            "note": " ".join(notes),
            "processes": [dict(self._processes[pid]) for pid in sorted(self._processes)],
            "sampled_tree_peak_rss_bytes": self._tree_peak,
            "sample_count": self._sample_count,
        }
