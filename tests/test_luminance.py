import numpy as np
import pytest

from aovguard.core.luminance import (
    ACESCG,
    AP1,
    REC601,
    REC709,
    LuminanceWeights,
    compute_luminance,
    luminance_weights_for_model,
)


def test_compute_luminance_acescg_unit_primaries() -> None:
    image = np.eye(3, dtype=np.float64).reshape(1, 3, 3)

    luminance = compute_luminance(image, ACESCG)

    np.testing.assert_allclose(
        luminance, [[0.2722287168, 0.6740817658, 0.0536895174]], rtol=0, atol=1e-12
    )
    assert sum((ACESCG.r, ACESCG.g, ACESCG.b)) == pytest.approx(1.0)
    assert AP1 is ACESCG


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("rec709", REC709),
        ("Rec.709", REC709),
        ("Rec.601", REC601),
        ("acescg", ACESCG),
        ("ACEScg", ACESCG),
        ("AP1", ACESCG),
    ],
)
def test_luminance_model_resolution(model: str, expected: LuminanceWeights) -> None:
    assert luminance_weights_for_model(model) == expected


def test_luminance_model_resolution_rejects_unknown_model() -> None:
    with pytest.raises(ValueError, match="Unknown luminance model"):
        luminance_weights_for_model("sRGB-display")


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

    with pytest.raises(ValueError, match="booleans"):
        LuminanceWeights.from_values((True, 0.0, 0.0))

    with pytest.raises(ValueError, match="positive sum"):
        LuminanceWeights.from_values((1e308, 1e308, 1e308), normalize=True)


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
