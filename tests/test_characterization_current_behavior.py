from pathlib import Path

import numpy as np
import pytest

from aovguard.cli import _count_simple_frames
from aovguard.multilayer import _compute_metrics as compute_multilayer_metrics
from aovguard.simple import _compute_metrics as compute_simple_metrics
from aovguard.simple import _read_exr, analyze_simple


def test_simple_metrics_interpret_opencv_bgr_as_rgb_luminance() -> None:
    image_bgr = np.array([[[3.0, 2.0, 1.0]]], dtype=np.float32)

    ratio, avg_lum, max_lum = compute_simple_metrics(image_bgr)

    assert ratio == 1.0
    assert avg_lum == pytest.approx(1.8596)
    assert max_lum == pytest.approx(1.8596)


def test_multilayer_metrics_interpret_openexr_channels_as_rgb_luminance() -> None:
    image_rgb = np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32)

    ratio, avg_lum, max_lum = compute_multilayer_metrics(image_rgb)

    assert ratio == 1.0
    assert avg_lum == pytest.approx(1.8596)
    assert max_lum == pytest.approx(1.8596)


def test_analyze_simple_empty_folder_returns_no_results(tmp_path: Path) -> None:
    assert analyze_simple(tmp_path) == []


def test_current_simple_frame_count_prefers_direct_frames(tmp_path: Path) -> None:
    direct = tmp_path / "shot.1001.exr"
    nested = tmp_path / "beauty" / "shot.1002.exr"
    nested.parent.mkdir()
    direct.write_bytes(b"")
    nested.write_bytes(b"")

    assert _count_simple_frames(tmp_path) == 1


def test_read_exr_reports_invalid_file_as_runtime_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.exr"
    path.write_text("not an exr")

    with pytest.raises(RuntimeError, match="Could not read EXR"):
        _read_exr(path)
