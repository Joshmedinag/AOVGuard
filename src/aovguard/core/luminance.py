"""Luminance weighting models and numerically stable RGB conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass(frozen=True, slots=True)
class LuminanceWeights:
    """RGB luminance coefficients."""

    r: float
    g: float
    b: float

    @classmethod
    def from_values(
        cls,
        values: Iterable[float],
        *,
        normalize: bool = False,
    ) -> "LuminanceWeights":
        """Validate optional normalization of three caller-provided weights."""

        raw_values = tuple(values)
        if any(isinstance(value, bool) for value in raw_values):
            raise ValueError("Luminance weights must be finite numbers, not booleans.")
        vals = tuple(float(v) for v in raw_values)
        if len(vals) != 3:
            raise ValueError("Luminance weights must contain exactly three values.")
        if not all(np.isfinite(vals)):
            raise ValueError("Luminance weights must be finite numbers.")

        total = sum(vals)
        if not np.isfinite(total) or total <= 0:
            raise ValueError("Luminance weights must have a positive sum.")

        if normalize:
            vals = tuple(v / total for v in vals)
        return cls(*vals)

    def as_array(self, dtype: np.dtype | type[np.floating] = np.float32) -> np.ndarray:
        """Return coefficients in the calculation dtype selected by the caller."""

        return np.array([self.r, self.g, self.b], dtype=dtype)


REC709 = LuminanceWeights(0.2126, 0.7152, 0.0722)
REC601 = LuminanceWeights(0.299, 0.587, 0.114)
# The Y row of the ACES AP1 RGB-to-XYZ matrix for scene-linear ACEScg.
ACESCG = LuminanceWeights(0.2722287168, 0.6740817658, 0.0536895174)
AP1 = ACESCG


def luminance_weights_for_model(model: str) -> LuminanceWeights:
    """Resolve a named linear-RGB model without converting the source color space.

    Rec.709, Rec.601 and ACEScg/AP1 identify the source primaries. The caller
    must select the model matching its scene-linear RGB input.
    """

    models = {"rec709": REC709, "rec601": REC601, "acescg": ACESCG, "ap1": ACESCG}
    key = model.strip().lower().replace(".", "")
    try:
        return models[key]
    except KeyError as exc:
        raise ValueError(f"Unknown luminance model: {model!r}.") from exc


def compute_luminance(
    image_rgb: np.ndarray,
    weights: LuminanceWeights | Iterable[float] = REC709,
) -> np.ndarray:
    """Compute luminance from an RGB image using explicit channel order.

    A 2D array is treated as already-luminance data. RGB/RGBA inputs must use
    RGB channel order; alpha and extra channels are ignored.
    """

    image = np.asarray(image_rgb)
    if image.ndim == 2:
        if np.issubdtype(image.dtype, np.floating):
            return image
        return image.astype(np.float64, copy=False)
    if image.ndim < 2 or image.shape[-1] < 3:
        raise ValueError("Expected a 2D image or an image with at least RGB channels.")

    if not isinstance(weights, LuminanceWeights):
        weights = LuminanceWeights.from_values(weights)

    calculation_dtype = np.float64 if image.dtype.itemsize > 4 else np.float32
    rgb = image[..., :3].astype(calculation_dtype, copy=False)
    return np.tensordot(
        rgb,
        weights.as_array(calculation_dtype),
        axes=([-1], [0]),
    )
