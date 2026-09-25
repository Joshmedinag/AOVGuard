from pathlib import Path

import cv2
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


def test_simple_reader_handles_grayscale_and_rgba(monkeypatch: pytest.MonkeyPatch) -> None:
    grayscale = np.ones((2, 2), dtype=np.float16)
    monkeypatch.setattr(cv2, "imread", lambda *args: grayscale)
    gray_result = _read_exr(Path("gray.exr"))
    assert gray_result.shape == (2, 2, 3)
    assert gray_result.dtype == np.float32

    rgba = np.ones((2, 2, 4), dtype=np.float32)
    monkeypatch.setattr(cv2, "imread", lambda *args: rgba)
    rgba_result = _read_exr(Path("rgba.exr"))
    assert rgba_result.shape == (2, 2, 3)


def test_simple_reader_wraps_opencv_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args):
        raise cv2.error("decode failed")

    monkeypatch.setattr(cv2, "imread", fail)

    with pytest.raises(RuntimeError, match="Could not read EXR"):
        _read_exr(Path("broken.exr"))


def test_simple_nested_analysis_groups_frames_and_reports_progress(tmp_path: Path) -> None:
    key = tmp_path / "keyLight"
    empty = tmp_path / "emptyLight"
    ignored = tmp_path / "ignored"
    key.mkdir()
    empty.mkdir()
    ignored.mkdir()
    for frame_number in (1001, 1002):
        assert cv2.imwrite(
            str(key / f"key.{frame_number}.exr"),
            np.ones((2, 2, 3), dtype=np.float32),
        )
        assert cv2.imwrite(
            str(empty / f"empty.{frame_number}.exr"),
            np.zeros((2, 2, 3), dtype=np.float32),
        )
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
