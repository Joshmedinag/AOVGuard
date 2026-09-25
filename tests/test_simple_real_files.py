from pathlib import Path

import cv2
import numpy as np

from aovguard.simple import analyze_simple


def test_analyze_simple_direct_exr_file(tmp_path: Path):
    image = np.ones((8, 8, 3), dtype=np.float32) * 0.25
    exr_path = tmp_path / "beauty.0001.exr"
    assert cv2.imwrite(str(exr_path), image)

    results = analyze_simple(tmp_path)

    assert len(results) == 1
    assert results[0].aov_name == "beauty.0001"
    assert results[0].classification == "Active"
    assert results[0].non_black_ratio == 1.0
