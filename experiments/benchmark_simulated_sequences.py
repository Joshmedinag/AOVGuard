"""Benchmark long sequences through a deterministic in-memory reader."""

from __future__ import annotations

import argparse
import gc
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Collection
from unittest.mock import patch

import numpy as np

from aovguard.core.analysis import analyze
from aovguard.core.models import (
    AnalysisOptions,
    AOVCategory,
    AOVDescriptor,
    FileInspection,
    FrameData,
)
from aovguard.discovery.frame_discovery import FrameDiscoveryResult


class SimulatedReader:
    """Deterministic in-memory reader used without creating EXR fixtures."""

    def __init__(self, width: int = 64, height: int = 36) -> None:
        """Allocate one reusable synthetic color frame at the requested size."""

        self.width = width
        self.height = height
        self._pixels = np.ones((height, width, 3), dtype=np.float32)

    def read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
    ) -> FrameData:
        """Return deterministic frame data without reading or writing an EXR."""

        descriptor = AOVDescriptor(
            name="beauty",
            channels=("R", "G", "B"),
            category=AOVCategory.COLOR,
            category_confidence="simulated_benchmark",
        )
        inspection = FileInspection(
            path=path,
            width=self.width,
            height=self.height,
            channels=descriptor.channels,
            aovs=(descriptor,),
        )
        return FrameData(
            path=path,
            width=self.width,
            height=self.height,
            inspection=inspection,
            channels=descriptor.channels,
            aovs={"beauty": self._pixels},
        )


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Elapsed time and Python-tracked memory for one frame count."""

    frame_count: int
    elapsed_seconds: float
    peak_megabytes: float
    processed_frames: int


def benchmark_sequence(frame_count: int) -> BenchmarkResult:
    """Measure sequential incremental analysis for an in-memory frame count."""

    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    source = Path("simulated-sequence")
    frames = tuple(source / f"shot.{1001 + index:06d}.exr" for index in range(frame_count))
    discovery = FrameDiscoveryResult(
        source=source,
        frames=frames,
        direct_frames=frames,
        nested_frames=(),
    )
    reader = SimulatedReader()
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    with patch("aovguard.core.analysis.discover_frames", return_value=discovery):
        report = analyze(source, AnalysisOptions(), reader)
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return BenchmarkResult(
        frame_count=frame_count,
        elapsed_seconds=elapsed,
        peak_megabytes=peak / (1024 * 1024),
        processed_frames=report.frame_count,
    )


def main() -> int:
    """Run requested frame counts and print compact CSV results."""

    parser = argparse.ArgumentParser(
        description=(
            "Benchmark AOVGuard with simulated in-memory frames; no EXR files are created."
        )
    )
    parser.add_argument(
        "--frames",
        nargs="+",
        type=int,
        default=(100, 500, 1000),
        help="Frame counts to measure (default: 100 500 1000).",
    )
    args = parser.parse_args()
    print("frames,processed,seconds,peak_mb")
    for frame_count in args.frames:
        result = benchmark_sequence(frame_count)
        print(
            f"{result.frame_count},{result.processed_frames},"
            f"{result.elapsed_seconds:.6f},{result.peak_megabytes:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
