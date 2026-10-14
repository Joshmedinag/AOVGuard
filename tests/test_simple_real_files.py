from pathlib import Path

import numpy as np
import OpenEXR
import pytest

from aovguard.simple import analyze_simple


def test_analyze_simple_direct_exr_file(tmp_path: Path):
    exr_path = tmp_path / "beauty.0001.exr"
    channels = {
        name: np.full((8, 8), 0.25, dtype=np.float32) for name in ("R", "G", "B")
    }
    OpenEXR.File({}, channels).write(str(exr_path))

    results = analyze_simple(tmp_path)

    assert len(results) == 1
    assert results[0].aov_name == "beauty.0001"
    assert results[0].classification == "Active"
    assert results[0].non_black_ratio == 1.0
    assert results[0].avg_luminance == pytest.approx(0.25)
