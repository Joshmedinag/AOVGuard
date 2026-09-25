import numpy as np
import pytest

from aovguard.core.channel_utils import normalize_color_to_rgb


def test_normalize_color_to_rgb_keeps_rgb_order() -> None:
    image = np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32)

    rgb = normalize_color_to_rgb(image, source_order="RGB")

    np.testing.assert_allclose(rgb, image)


def test_normalize_color_to_rgb_converts_bgr_order() -> None:
    image_bgr = np.array([[[3.0, 2.0, 1.0]]], dtype=np.float32)

    rgb = normalize_color_to_rgb(image_bgr, source_order="BGR")

    np.testing.assert_allclose(rgb, np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32))


def test_normalize_color_to_rgb_ignores_alpha() -> None:
    image_bgra = np.array([[[3.0, 2.0, 1.0, 0.5]]], dtype=np.float32)

    rgb = normalize_color_to_rgb(image_bgra, source_order="BGRA")

    np.testing.assert_allclose(rgb, np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32))


def test_normalize_color_to_rgb_ignores_unnamed_extra_channels() -> None:
    image = np.array([[[1.0, 2.0, 3.0, 0.5, 42.0]]], dtype=np.float32)

    rgb = normalize_color_to_rgb(image, source_order="RGBA")

    np.testing.assert_allclose(rgb, np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32))


def test_normalize_color_to_rgb_expands_grayscale() -> None:
    image = np.array([[0.25, 0.5]], dtype=np.float32)

    rgb = normalize_color_to_rgb(image)

    expected = np.array([[[0.25, 0.25, 0.25], [0.5, 0.5, 0.5]]], dtype=np.float32)
    np.testing.assert_allclose(rgb, expected)


def test_normalize_color_to_rgb_rejects_missing_channels() -> None:
    image = np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32)

    with pytest.raises(ValueError, match="missing RGB"):
        normalize_color_to_rgb(image, source_order="RGA")


def test_normalize_color_to_rgb_rejects_too_few_channels() -> None:
    image = np.array([[[1.0, 2.0]]], dtype=np.float32)

    with pytest.raises(ValueError, match="at least three"):
        normalize_color_to_rgb(image)
