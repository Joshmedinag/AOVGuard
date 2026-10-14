"""Regression tests for native-memory measurements and process isolation."""

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import OpenEXR
import pytest

from aovguard.core.memory import MEMORY_MODEL_VERSION
from aovguard.io.inspector import build_file_inspection
from experiments import benchmark_memory


@pytest.mark.parametrize("system,multiplier", [("Darwin", 1), ("Linux", 1024)])
def test_posix_peak_memory_units_are_normalized_to_bytes(
    monkeypatch: pytest.MonkeyPatch, system: str, multiplier: int,
) -> None:
    resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _who: SimpleNamespace(ru_maxrss=123))
    monkeypatch.setitem(sys.modules, "resource", resource)

    assert benchmark_memory.peak_rss_bytes(system) == 123 * multiplier


def test_windows_memory_path_uses_the_native_high_water_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmark_memory, "_windows_peak_rss_bytes", lambda: 987_654)

    assert benchmark_memory.peak_rss_bytes("Windows") == 987_654


def test_worker_is_launched_in_a_fresh_interpreter_with_safe_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "EXR source & spaces"
    captured: dict = {}

    def fake_run(command: list[str], **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout='{"counts":{"processed_frames":1}}', stderr="")

    monkeypatch.setattr(benchmark_memory.subprocess, "run", fake_run)

    result = benchmark_memory.run_isolated_benchmark(source, max_frames=2, recursive=True)

    assert captured["command"][0] == sys.executable
    assert captured["command"][1] == "-B"
    assert str(source.resolve()) in captured["command"]
    assert "--worker" in captured["command"]
    assert captured["command"][-3:] == ["--max-frames", "2", "--recursive"]
    assert captured["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "shell" not in captured
    assert result["counts"]["processed_frames"] == 1
    assert result["worker_exit_code"] == 0


def test_invalid_worker_output_is_reported_without_a_traceback(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        benchmark_memory.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=9, stdout="", stderr="native failure"),
    )

    assert benchmark_memory.main(["existing.exr"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["type"] == "RuntimeError"
    assert "native failure" in result["error"]["message"]


def test_invalid_max_frames_is_rejected_before_analysis() -> None:
    with pytest.raises(SystemExit) as error:
        benchmark_memory.main(["existing.exr", "--max-frames", "0"])
    assert error.value.code == 2


def test_isolated_memory_benchmark_reads_a_temporary_real_exr_without_changing_it(tmp_path: Path) -> None:
    source = tmp_path / "shot.0001.exr"
    OpenEXR.File({}, {
        name: np.ones((2, 2), dtype=np.float32) for name in ("R", "G", "B")
    }).write(str(source))
    before = source.read_bytes()

    result = benchmark_memory.run_isolated_benchmark(source, max_frames=1)

    assert result["worker_exit_code"] == 0
    assert result["counts"]["processed_frames"] == 1
    assert result["counts"]["failed_frames"] == 0
    assert result["counts"]["unique_channels"] == 3
    assert result["memory"]["peak_rss_bytes"] > 0
    assert result["memory"]["includes_native_allocations"]
    assert result["memory"]["peak_rss_bytes"] >= result["memory"]["baseline_peak_rss_bytes"]
    estimate = result["memory"]["estimates"][str(source)]
    assert estimate["model_version"] == MEMORY_MODEL_VERSION
    assert estimate["channel_count"] == 3
    assert estimate["estimated_bytes"] == 80 * 1024 * 1024 + 400
    assert result["options"]["max_memory_mb"] is None
    assert result["runtime"]["isolated_process"]
    assert result["runtime"]["process_id"] != os.getpid()
    assert result["runtime"]["openexr"] == OpenEXR.__version__
    assert result["elapsed_seconds"] >= 0
    assert result["isolated_wall_seconds"] >= result["elapsed_seconds"]
    assert source.read_bytes() == before
    assert list(tmp_path.iterdir()) == [source]


def test_worker_failure_keeps_a_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        benchmark_memory.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout='{"error":{"type":"FileNotFoundError","message":"missing"}}', stderr="",
        ),
    )

    result = benchmark_memory.run_isolated_benchmark("missing.exr")

    assert result["worker_exit_code"] == 1
    assert result["error"]["type"] == "FileNotFoundError"


def test_memory_budget_is_forwarded_to_the_isolated_child(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def capture(command: list[str], **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(benchmark_memory.subprocess, "run", capture)

    benchmark_memory.run_isolated_benchmark("existing.exr", max_memory_mb=128.5)

    assert commands[0][-2:] == ["--max-memory-mb", "128.5"]


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_cli_memory_budgets_are_rejected_before_launch(value: str) -> None:
    with pytest.raises(SystemExit) as error:
        benchmark_memory.main(["existing.exr", "--max-memory-mb", value])
    assert error.value.code == 2


def test_rejected_native_frame_keeps_its_preflight_estimate_in_the_benchmark(tmp_path: Path) -> None:
    source = tmp_path / "shot.0001.exr"
    OpenEXR.File({}, {
        name: np.ones((2, 2), dtype=np.float32) for name in ("R", "G", "B")
    }).write(str(source))
    before = source.read_bytes()

    result = benchmark_memory.run_isolated_benchmark(source, max_memory_mb=1)

    assert result["worker_exit_code"] == 0
    assert result["counts"]["processed_frames"] == 0
    assert result["counts"]["failed_frames"] == 1
    assert result["options"]["max_memory_mb"] == 1.0
    assert result["memory"]["estimates"][str(source)]["estimated_mib"] > 1
    assert source.read_bytes() == before
    assert list(tmp_path.iterdir()) == [source]


def test_unavailable_deep_or_invalid_metadata_does_not_abort_calibration() -> None:
    deep = replace(
        build_file_inspection(path="deep.exr", width=1, height=1, channels=("Z",)),
        is_deep=True,
    )
    invalid = replace(deep, path=Path("invalid.exr"), is_deep=False, part_count=2)

    estimates = benchmark_memory._memory_estimates((deep, invalid))

    assert estimates["deep.exr"]["status"] == "unavailable"
    assert "Deep EXR" in estimates["deep.exr"]["reason"]
    assert estimates["invalid.exr"]["status"] == "unavailable"
    assert "requires every part" in estimates["invalid.exr"]["reason"]
    json.dumps(estimates, allow_nan=False)
