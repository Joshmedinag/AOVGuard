"""Measure native process peak memory while analyzing existing EXR sources.

The parent launches a fresh Python process for each measurement. The child
reads the supplied source and prints JSON; neither process generates EXRs,
reports or other output files. Peak RSS includes native OpenEXR/NumPy buffers
and the Python runtime, unlike tracemalloc's Python allocation accounting.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict
from importlib import import_module, metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aovguard.core.models import FileInspection


def _windows_peak_rss_bytes() -> int:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
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

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.PeakWorkingSetSize)


def peak_rss_bytes(system: str | None = None) -> int:
    """Return this process's resident-memory high-water mark in bytes.

    Windows uses PeakWorkingSetSize. POSIX uses ru_maxrss, whose units are
    bytes on macOS and KiB on Linux and the other supported Unix platforms.
    The optional system name is a test seam; normal callers use the host OS.
    """

    resolved_system = system or platform.system()
    if resolved_system == "Windows":
        return _windows_peak_rss_bytes()
    # Import dynamically because resource's POSIX APIs are absent from Windows
    # type stubs as well as from the Windows runtime.
    resource_module = import_module("resource")
    peak = resource_module.getrusage(resource_module.RUSAGE_SELF).ru_maxrss
    return int(peak) * (1 if resolved_system == "Darwin" else 1024)


def _memory_estimates(inspections: Sequence[FileInspection]) -> dict[str, dict[str, Any]]:
    from aovguard.core.memory import estimate_frame_memory

    estimates: dict[str, dict[str, Any]] = {}
    for inspection in inspections:
        if inspection.unsupported_reason is not None:
            estimates[str(inspection.path)] = {
                "status": "unavailable", "reason": inspection.unsupported_reason,
            }
            continue
        try:
            estimate = estimate_frame_memory(inspection)
        except ValueError as exc:
            estimates[str(inspection.path)] = {"status": "unavailable", "reason": str(exc)}
        else:
            estimates[str(inspection.path)] = asdict(estimate)
    return estimates


def benchmark_source(
    source: str | Path,
    *,
    max_frames: int | None = None,
    frame_pattern: str = "*.exr",
    recursive: bool = False,
    max_depth: int = 1,
    max_memory_mb: float | None = None,
) -> dict[str, Any]:
    """Analyze existing files and measure this fresh worker's time and peak RSS.

    ``max_frames`` is an upper bound on discovered files, matching the regular
    analyzer: an oversized source is rejected rather than silently sampled.
    The returned baseline is itself a high-water mark measured after imports;
    peak growth is not an instantaneous allocation delta or a leak estimate.
    Conservative per-frame estimates are calculated after capturing elapsed
    time and peak RSS, even when memory admission is disabled, for calibration.
    """

    import OpenEXR

    from aovguard.core.analysis import analyze
    from aovguard.core.models import AnalysisOptions
    from aovguard.io.reader import OpenEXRReader

    options = AnalysisOptions(
        max_frames=max_frames,
        frame_pattern=frame_pattern,
        recursive=recursive,
        max_depth=max_depth,
        allow_multiple_sequences=True,
        max_memory_mb=max_memory_mb,
    )
    baseline = peak_rss_bytes()
    started = time.perf_counter()
    report = analyze(source, options, OpenEXRReader())
    elapsed = time.perf_counter() - started
    peak = peak_rss_bytes()
    try:
        aovguard_version = metadata.version("aovguard")
    except metadata.PackageNotFoundError:
        aovguard_version = "unknown"
    return {
        "schema_version": "1.0",
        "benchmark": "aovguard-native-process-memory",
        "source": str(Path(source).resolve()),
        "elapsed_seconds": elapsed,
        "memory": {
            "peak_rss_bytes": peak,
            "peak_rss_mib": peak / (1024 * 1024),
            "baseline_peak_rss_bytes": baseline,
            "peak_growth_bytes": max(0, peak - baseline),
            "measurement": (
                "PROCESS_MEMORY_COUNTERS.PeakWorkingSetSize"
                if platform.system() == "Windows" else "getrusage(RUSAGE_SELF).ru_maxrss"
            ),
            "includes_native_allocations": True,
            "estimates": _memory_estimates(report.inspections),
        },
        "counts": {
            "discovered_frames": report.discovered_frame_count,
            "processed_frames": report.frame_count,
            "failed_frames": report.failed_frame_count,
            "color_aovs": len(report.metrics_by_aov),
            "technical_aovs": report.technical_aov_count,
            "unique_channels": len({
                channel for inspection in report.inspections for channel in inspection.channels
            }),
            "inspected_parts": sum(inspection.part_count for inspection in report.inspections),
            "findings": len(report.findings),
        },
        "frames": [
            {
                "path": str(inspection.path),
                "parts": [
                    {
                        "index": part.index,
                        "name": part.name,
                        "width": part.width,
                        "height": part.height,
                        "channel_count": len(part.channels),
                    }
                    for part in inspection.parts
                ],
            }
            for inspection in report.inspections
        ],
        "options": {
            "max_frames": max_frames,
            "frame_pattern": frame_pattern,
            "recursive": recursive,
            "max_depth": max_depth,
            "max_memory_mb": options.max_memory_mb,
        },
        "runtime": {
            "process_id": os.getpid(),
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "openexr": str(getattr(OpenEXR, "__version__", "unknown")),
            "aovguard": aovguard_version,
            "isolated_process": True,
        },
    }


def run_isolated_benchmark(
    source: str | Path,
    *,
    max_frames: int | None = None,
    frame_pattern: str = "*.exr",
    recursive: bool = False,
    max_depth: int = 1,
    max_memory_mb: float | None = None,
) -> dict[str, Any]:
    """Run one measurement in a fresh interpreter without using a shell."""

    command = [
        sys.executable, "-B", str(Path(__file__).resolve()), str(Path(source).resolve()),
        "--worker", "--frame-pattern", frame_pattern, "--max-depth", str(max_depth),
    ]
    if max_frames is not None:
        command.extend(("--max-frames", str(max_frames)))
    if max_memory_mb is not None:
        command.extend(("--max-memory-mb", str(max_memory_mb)))
    if recursive:
        command.append("--recursive")
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.perf_counter()
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=environment, check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Benchmark worker exited with code {completed.returncode} without valid JSON: "
            f"{completed.stderr.strip()}"
        ) from exc
    if not isinstance(result, dict):
        raise RuntimeError("Benchmark worker returned a non-object JSON result.")
    result["isolated_wall_seconds"] = time.perf_counter() - started
    result["worker_exit_code"] = completed.returncode
    if completed.returncode and completed.stderr.strip():
        result["worker_stderr"] = completed.stderr.strip()
    return result


def _positive_frames(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("max-frames must be positive")
    return number


def _positive_memory(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("max-memory-mb must be a positive finite MiB budget")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    """Read an existing source in an isolated process and print strict JSON."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Existing EXR file or directory; no EXRs are generated.")
    parser.add_argument(
        "--max-frames", type=_positive_frames,
        help="Reject sources exceeding this discovered-frame count; does not sample the source.",
    )
    parser.add_argument("--frame-pattern", default="*.exr", help="Filename glob for directory discovery.")
    parser.add_argument("--recursive", action="store_true", help="Discover subdirectories too.")
    parser.add_argument("--max-depth", type=int, default=1, help="Maximum recursive discovery depth.")
    parser.add_argument(
        "--max-memory-mb", type=_positive_memory,
        help="Optional conservative frame-admission budget in MiB; not a hard process RSS limit.",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        function = benchmark_source if args.worker else run_isolated_benchmark
        result = function(
            args.source, max_frames=args.max_frames, frame_pattern=args.frame_pattern,
            recursive=args.recursive, max_depth=args.max_depth,
            max_memory_mb=args.max_memory_mb,
        )
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "benchmark": "aovguard-native-process-memory",
            "source": str(args.source.resolve()),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if "error" in result or result.get("worker_exit_code", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
