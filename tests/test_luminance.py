import numpy as np
import pytest

from aovguard.core.luminance import (
    REC601,
    REC709,
    LuminanceWeights,
    compute_luminance,
)


def test_compute_luminance_rec709_rgb_order() -> None:
    image = np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32)

    luminance = compute_luminance(image, REC709)

    assert luminance.shape == (1, 1)
    assert luminance[0, 0] == pytest.approx(1.8596)


def test_compute_luminance_rec601_rgb_order() -> None:
    image = np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32)

    luminance = compute_luminance(image, REC601)

    assert luminance[0, 0] == pytest.approx(1.815)


def test_compute_luminance_custom_weights() -> None:
    image = np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32)

    luminance = compute_luminance(image, (0.25, 0.25, 0.5))

    assert luminance[0, 0] == pytest.approx(2.25)


def test_luminance_weights_can_normalize_custom_values() -> None:
    weights = LuminanceWeights.from_values((1.0, 2.0, 1.0), normalize=True)

    assert weights.r == pytest.approx(0.25)
    assert weights.g == pytest.approx(0.5)
    assert weights.b == pytest.approx(0.25)


def test_luminance_rejects_invalid_weights() -> None:
    with pytest.raises(ValueError, match="exactly three"):
        LuminanceWeights.from_values((1.0, 2.0))

    with pytest.raises(ValueError, match="finite"):
        LuminanceWeights.from_values((1.0, float("nan"), 0.0))

    with pytest.raises(ValueError, match="positive sum"):
        LuminanceWeights.from_values((0.0, 0.0, 0.0))


def test_compute_luminance_accepts_grayscale_as_already_luminance() -> None:
    image = np.array([[0.1, 0.2]], dtype=np.float32)

    luminance = compute_luminance(image)

    np.testing.assert_allclose(luminance, image)


def test_compute_luminance_preserves_float64_for_hdr_precision() -> None:
    image = np.asarray([[[100_000_000.0, 1.0, 1.0]]], dtype=np.float64)

    result = compute_luminance(image, (1.0, 1.0, 1.0))

    assert result.dtype == np.float64
    assert result[0, 0] == pytest.approx(100_000_002.0)


def test_compute_luminance_rejects_one_dimensional_data() -> None:
    with pytest.raises(ValueError, match="at least RGB channels"):
        compute_luminance(np.array([1.0, 2.0, 3.0], dtype=np.float32))
