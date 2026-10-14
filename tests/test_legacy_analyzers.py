from pathlib import Path

import Imath
import numpy as np
import OpenEXR
import pytest

from aovguard.multilayer import (
    _list_rgb_aovs,
    _read_rgb_aov,
    analyze_multilayer,
    inspect_exr,
)
from aovguard.simple import _read_exr, analyze_simple


def _channel(value: float, width: int, height: int) -> bytes:
    return np.full((height, width), value, dtype=np.float32).tobytes()


def _write_exr(
    path: Path,
    channels: dict[str, float],
    *,
    width: int = 2,
    height: int = 2,
) -> Path:
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(width, height)
    header["channels"] = {name: Imath.Channel(pixel_type) for name in channels}
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {name: _channel(value, width, height) for name, value in channels.items()}
        )
    finally:
        output.close()
    return path


def _multilayer_channels(diffuse: float, emission: float = 0.0) -> dict[str, float]:
    return {
        "R": 0.25,
        "G": 0.25,
        "B": 0.25,
        "diffuse.R": diffuse,
        "diffuse.G": diffuse,
        "diffuse.B": diffuse,
        "emission.R": emission,
        "emission.G": emission,
        "emission.B": emission,
        "incomplete.R": 1.0,
        "incomplete.G": 1.0,
        "crypto.A": 1.0,
    }


def test_legacy_multilayer_inspection_and_named_channel_read(tmp_path: Path) -> None:
    path = _write_exr(tmp_path / "shot.1001.exr", _multilayer_channels(0.5))

    text = inspect_exr(path)
    names = _list_rgb_aovs(path)
    diffuse = _read_rgb_aov(path, "diffuse")

    assert "Part size: 2x2" in text
    assert "diffuse.R" in text
    assert "Detected RGB AOV groups" in text
    assert names == ["diffuse", "emission"]
    assert diffuse.shape == (2, 2, 3)
    np.testing.assert_allclose(diffuse, 0.5)


def test_legacy_multilayer_analysis_aggregates_frames_and_progress(tmp_path: Path) -> None:
    _write_exr(tmp_path / "shot.1001.exr", _multilayer_channels(1.0))
    _write_exr(tmp_path / "shot.1002.exr", _multilayer_channels(0.0))
    progress: list[tuple[int, int, str]] = []

    results = analyze_multilayer(
        tmp_path,
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )

    by_name = {result.aov_name: result for result in results}
    assert set(by_name) == {"diffuse", "emission"}
    assert by_name["diffuse"].classification == "Active"
    assert by_name["diffuse"].non_black_ratio == 0.5
    assert by_name["diffuse"].avg_luminance == pytest.approx(0.5)
    assert by_name["emission"].classification == "Empty"
    assert len(progress) == 4
    assert progress[-1][:2] == (4, 4)


def test_legacy_multilayer_reports_input_and_structure_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Input folder"):
        analyze_multilayer(tmp_path / "missing")

    file_path = tmp_path / "not_a_folder.exr"
    file_path.write_bytes(b"")
    with pytest.raises(NotADirectoryError, match="not a folder"):
        analyze_multilayer(file_path)

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="No EXR files"):
        analyze_multilayer(empty)

    root_only = tmp_path / "root_only"
    root_only.mkdir()
    _write_exr(root_only / "beauty.exr", {"R": 1.0, "G": 1.0, "B": 1.0})
    with pytest.raises(RuntimeError, match="No RGB AOV groups"):
        analyze_multilayer(root_only)


def test_legacy_multilayer_read_reports_missing_channel(tmp_path: Path) -> None:
    path = _write_exr(
        tmp_path / "incomplete.exr",
        {"diffuse.R": 1.0, "diffuse.G": 1.0},
    )

    with pytest.raises(RuntimeError, match="Missing channel diffuse.B"):
        _read_rgb_aov(path, "diffuse")


@pytest.mark.parametrize("dtype", [np.float16, np.float32])
def test_simple_reader_handles_grayscale_and_rgba(tmp_path: Path, dtype) -> None:
    grayscale_path = tmp_path / "gray.exr"
    grayscale = np.full((2, 2), 0.5, dtype=dtype)
    OpenEXR.File({}, {"Y": grayscale}).write(str(grayscale_path))
    gray_result = _read_exr(grayscale_path)
    assert gray_result.shape == (2, 2, 3)
    assert gray_result.dtype == np.float32
    np.testing.assert_allclose(gray_result, 0.5)

    rgba_path = _write_exr(
        tmp_path / "rgba.exr", {"R": 1.0, "G": 2.0, "B": 3.0, "A": 0.0}
    )
    rgba_result = _read_exr(rgba_path)
    assert rgba_result.shape == (2, 2, 3)
    np.testing.assert_allclose(rgba_result, np.tile([3.0, 2.0, 1.0], (2, 2, 1)))
    result = analyze_simple(tmp_path)
    rgba_metrics = next(row for row in result if row.aov_name == "rgba")
    assert rgba_metrics.avg_luminance == pytest.approx(1.8596)


def test_simple_reader_wraps_openexr_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(OpenEXR, "File", fail)

    with pytest.raises(RuntimeError, match="Could not read EXR"):
        _read_exr(Path("broken.exr"))


def test_simple_reader_rejects_multipart_without_truncating(tmp_path: Path) -> None:
    path = tmp_path / "multipart.exr"
    channels = {name: np.ones((2, 2), np.float32) for name in ("R", "G", "B")}
    OpenEXR.File([
        OpenEXR.Part({}, channels, "left"),
        OpenEXR.Part({}, channels, "right"),
    ]).write(str(path))

    with pytest.raises(RuntimeError, match="Could not read EXR") as error:
        _read_exr(path)
    assert "single-part" in str(error.value.__cause__)


def test_simple_reader_rejects_non_rgb_or_grayscale_channels(tmp_path: Path) -> None:
    path = _write_exr(tmp_path / "technical.exr", {"N.X": 1.0, "N.Y": 0.0})

    with pytest.raises(RuntimeError, match="Could not read EXR"):
        _read_exr(path)


def test_simple_nested_analysis_groups_frames_and_reports_progress(tmp_path: Path) -> None:
    key = tmp_path / "keyLight"
    empty = tmp_path / "emptyLight"
    ignored = tmp_path / "ignored"
    key.mkdir()
    empty.mkdir()
    ignored.mkdir()
    for frame_number in (1001, 1002):
        _write_exr(key / f"key.{frame_number}.exr", {"R": 1.0, "G": 1.0, "B": 1.0})
        _write_exr(empty / f"empty.{frame_number}.exr", {"R": 0.0, "G": 0.0, "B": 0.0})
    progress: list[tuple[int, int, str]] = []

    results = analyze_simple(
        tmp_path,
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )

    by_name = {result.aov_name: result for result in results}
    assert by_name["keyLight"].classification == "Active"
    assert by_name["emptyLight"].classification == "Empty"
    assert len(progress) == 4
    assert progress[-1][0] == 4
    assert all(total == 4 for _, total, _ in progress)


def test_simple_analysis_rejects_missing_and_file_sources(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        analyze_simple(tmp_path / "missing")

    file_path = tmp_path / "frame.exr"
    file_path.write_bytes(b"")
    with pytest.raises(NotADirectoryError):
        analyze_simple(file_path)
