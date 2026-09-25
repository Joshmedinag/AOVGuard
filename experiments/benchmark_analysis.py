from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Collection

import Imath
import numpy as np
import OpenEXR

from aovguard.io.reader import OpenEXRReader


@dataclass(frozen=True, slots=True)
class RunMeasurement:
    seconds: float
    python_peak_bytes: int
    read_calls: int
    checksum: float


class CountingReader:
    def __init__(self) -> None:
        self.reader = OpenEXRReader()
        self.read_calls = 0

    def read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
    ):
        self.read_calls += 1
        return self.reader.read_frame(path, requested_aovs=requested_aovs)


def _write_benchmark_exr(
    path: Path,
    *,
    width: int,
    height: int,
    aov_count: int,
    frame_index: int,
) -> None:
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    base = np.broadcast_to(x, (height, width)) + np.broadcast_to(y, (height, width))
    base = np.ascontiguousarray(base + frame_index * 0.001, dtype=np.float32)

    channels: dict[str, np.ndarray] = {
        "R": base * 0.5,
        "G": base * 0.35,
        "B": base * 0.15,
    }
    for index in range(1, aov_count):
        scale = np.float32((index + 1) / aov_count)
        name = f"aov_{index:02d}"
        channels[f"{name}.R"] = np.ascontiguousarray(base * scale)
        channels[f"{name}.G"] = np.ascontiguousarray(base * scale * 0.8)
        channels[f"{name}.B"] = np.ascontiguousarray(base * scale * 0.6)

    path.parent.mkdir(parents=True, exist_ok=True)
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(width, height)
    header["channels"] = {
        name: Imath.Channel(pixel_type)
        for name in channels
    }
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels({name: values.tobytes() for name, values in channels.items()})
    finally:
        output.close()


def create_dataset(
    directory: Path,
    *,
    frame_count: int,
    width: int,
    height: int,
    aov_count: int,
) -> tuple[Path, ...]:
    frames: list[Path] = []
    for index in range(frame_count):
        path = directory / f"benchmark.{1001 + index:04d}.exr"
        _write_benchmark_exr(
            path,
            width=width,
            height=height,
            aov_count=aov_count,
            frame_index=index,
        )
        frames.append(path)
    return tuple(frames)


def _measure(operation: Callable[[CountingReader], float]) -> RunMeasurement:
    reader = CountingReader()
    tracemalloc.start()
    start = time.perf_counter()
    checksum = operation(reader)
    seconds = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return RunMeasurement(seconds, peak, reader.read_calls, checksum)


def _aov_first(frames: tuple[Path, ...], aov_names: tuple[str, ...]):
    def run(reader: CountingReader) -> float:
        checksum = 0.0
        for aov_name in aov_names:
            for path in frames:
                frame = reader.read_frame(path, requested_aovs=(aov_name,))
                checksum += float(np.sum(frame.aovs[aov_name], dtype=np.float64))
        return checksum

    return run


def _frame_first(frames: tuple[Path, ...], aov_names: tuple[str, ...]):
    def run(reader: CountingReader) -> float:
        checksum = 0.0
        for path in frames:
            frame = reader.read_frame(path)
            for aov_name in aov_names:
                checksum += float(np.sum(frame.aovs[aov_name], dtype=np.float64))
        return checksum

    return run


def _summary(measurements: list[RunMeasurement]) -> dict[str, float | int]:
    seconds = [item.seconds for item in measurements]
    q1, _, q3 = statistics.quantiles(seconds, n=4, method="inclusive")
    return {
        "median_seconds": statistics.median(seconds),
        "min_seconds": min(seconds),
        "q1_seconds": q1,
        "q3_seconds": q3,
        "iqr_seconds": q3 - q1,
        "median_python_peak_bytes": int(
            statistics.median(item.python_peak_bytes for item in measurements)
        ),
        "read_calls": measurements[0].read_calls,
        "checksum": measurements[0].checksum,
    }


def benchmark(
    *,
    data_dir: Path,
    frame_count: int,
    width: int,
    height: int,
    aov_count: int,
    repeats: int,
) -> dict[str, object]:
    frames = create_dataset(
        data_dir,
        frame_count=frame_count,
        width=width,
        height=height,
        aov_count=aov_count,
    )
    inspection = OpenEXRReader().inspect(frames[0])
    aov_names = tuple(
        descriptor.name
        for descriptor in inspection.aovs
        if descriptor.category.value == "color"
    )
    if len(aov_names) != aov_count:
        raise RuntimeError(f"Expected {aov_count} color AOVs, found {len(aov_names)}.")

    aov_first_operation = _aov_first(frames, aov_names)
    frame_first_operation = _frame_first(frames, aov_names)

    # Unrecorded warm-up runs avoid measuring first-use import and allocation costs.
    _measure(aov_first_operation)
    _measure(frame_first_operation)

    old_runs: list[RunMeasurement] = []
    new_runs: list[RunMeasurement] = []
    for index in range(repeats):
        # Alternating the order balances cache and background-system effects.
        if index % 2 == 0:
            old_runs.append(_measure(aov_first_operation))
            new_runs.append(_measure(frame_first_operation))
        else:
            new_runs.append(_measure(frame_first_operation))
            old_runs.append(_measure(aov_first_operation))
    old_summary = _summary(old_runs)
    new_summary = _summary(new_runs)
    checksums_match = bool(
        np.isclose(old_summary["checksum"], new_summary["checksum"], rtol=1e-9)
    )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "openexr": getattr(OpenEXR, "__version__", "unknown"),
        },
        "dataset": {
            "frames": frame_count,
            "aovs": aov_count,
            "width": width,
            "height": height,
            "repeats": repeats,
        },
        "aov_first": old_summary,
        "frame_first": new_summary,
        "comparison": {
            "checksums_match": checksums_match,
            "read_call_reduction_factor": old_summary["read_calls"] / new_summary["read_calls"],
            "median_speedup_factor": old_summary["median_seconds"] / new_summary["median_seconds"],
        },
        "measurement_notes": [
            "Read calls are calls made by AOVGuard to the reader, not operating-system file opens.",
            "Python peak memory is measured with tracemalloc and excludes native allocations made by OpenEXR.",
            "One unrecorded warm-up run was completed for each strategy.",
            "Strategy order alternated on each repetition to balance cache and order effects.",
            "Timing is machine-dependent; medians and interquartile ranges are reported instead of a universal performance claim.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare AOV-first and frame-first EXR reading.")
    parser.add_argument("--data-dir", type=Path, default=Path("experiments/_benchmark_data"))
    parser.add_argument("--output", type=Path, default=Path("experiments/benchmark_results.json"))
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--aovs", type=int, default=5)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=180)
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()

    if min(args.frames, args.aovs, args.width, args.height, args.repeats) <= 0:
        parser.error("All numeric arguments must be positive.")

    result = benchmark(
        data_dir=args.data_dir,
        frame_count=args.frames,
        width=args.width,
        height=args.height,
        aov_count=args.aovs,
        repeats=args.repeats,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
