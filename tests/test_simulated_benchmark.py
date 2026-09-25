from __future__ import annotations

import pytest

from experiments.benchmark_simulated_sequences import benchmark_sequence


@pytest.mark.parametrize("frame_count", [100, 500, 1000])
def test_simulated_benchmark_processes_large_sequences_without_exr_files(
    frame_count: int,
) -> None:
    result = benchmark_sequence(frame_count)

    assert result.frame_count == frame_count
    assert result.processed_frames == frame_count
    assert result.elapsed_seconds >= 0.0
    assert result.peak_megabytes > 0.0
