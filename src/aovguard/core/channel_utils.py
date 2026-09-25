"""Helpers for normalizing and grouping named EXR channels."""

from __future__ import annotations

import numpy as np


def normalize_color_to_rgb(
    image: np.ndarray,
    *,
    source_order: str = "RGB",
) -> np.ndarray:
    """Return image data as float32 RGB.

    Grayscale inputs are expanded to RGB. For multi-channel inputs, *source_order*
    describes the incoming channel order, such as "RGB", "BGR", "RGBA", or
    "BGRA". Alpha and extra channels are ignored.
    """

    array = np.asarray(image)
    if array.ndim == 2:
        return np.stack([array, array, array], axis=-1).astype(np.float32, copy=False)
    if array.ndim < 2 or array.shape[-1] < 3:
        raise ValueError("Expected a 2D image or an image with at least three channels.")

    order = source_order.upper()
    if len(order) < array.shape[-1]:
        order = order[: array.shape[-1]]
    missing = [channel for channel in "RGB" if channel not in order]
    if missing:
        raise ValueError(f"Source order is missing RGB channel(s): {', '.join(missing)}")

    indices = [order.index(channel) for channel in "RGB"]
    return array[..., indices].astype(np.float32, copy=False)
