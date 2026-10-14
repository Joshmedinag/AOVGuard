"""Transparent conservative preflight estimates for flat OpenEXR working sets.

This model is an admission estimate, not an RSS guarantee. It reserves space
for every physical channel regardless of AOV category or requested selection.
Native decoder internals, allocator behavior, the accumulated report, GUI
objects and other concurrent jobs are not fully bounded by these formulas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from aovguard.core.models import FileInspection, PartInspection

MEMORY_MODEL_VERSION: Final[str] = "flat-working-set-v1"
MIB_BYTES: Final[int] = 1024 * 1024
# Header-only channel types are unavailable reliably across supported bindings.
# Reserve four bytes for each native HALF/FLOAT/UINT sample and another four
# for the worst-case HALF-to-float32 promotion retained alongside native data.
NATIVE_BYTES_PER_SAMPLE: Final[int] = 4
HALF_PROMOTION_BYTES_PER_SAMPLE: Final[int] = 4
# Mixed FLOAT/UINT semantic stacks can promote to float64. Count all physical
# channels, including single-channel views and alpha/AUX not used in RGB stacks,
# to avoid an optimistic estimate based on semantic classification or filtering.
AOV_STACK_BYTES_PER_SAMPLE: Final[int] = 8
# Channel reductions and color luminance operate sequentially. Reserve scratch
# arrays against the largest stored part, rather than its display/delivery size.
SCRATCH_BYTES_PER_PIXEL: Final[int] = 32
# This fixed reserve covers a modest runtime/header overhead; the process's
# existing RSS, long report history and GUI memory may exceed it substantially.
FIXED_RESERVE_BYTES: Final[int] = 64 * MIB_BYTES
SAFETY_FACTOR: Final[float] = 1.25
_SAFETY_NUMERATOR: Final[int] = 5
_SAFETY_DENOMINATOR: Final[int] = 4


@dataclass(frozen=True, slots=True)
class MemoryEstimate:
    """Scalar, JSON-serializable breakdown of the flat working-set estimate.

    Byte totals use Python integers and integer ceiling arithmetic. MiB is a
    convenient approximate display value. ``estimated_bytes`` remains the
    authoritative total when comparing or recording large estimates.
    """

    model_version: str
    part_count: int
    channel_count: int
    native_channel_bytes: int
    half_promotion_bytes: int
    aov_stack_bytes: int
    scratch_bytes: int
    fixed_reserve_bytes: int
    subtotal_bytes: int
    safety_margin_bytes: int
    estimated_bytes: int
    estimated_mib: float
    safety_factor: float


class MemoryBudgetExceeded(RuntimeError):
    """A frame's conservative preflight estimate exceeds its admission budget."""

    def __init__(
        self,
        inspection: FileInspection,
        estimate: MemoryEstimate,
        max_memory_mb: float,
    ) -> None:
        """Retain structured rejection evidence without allocating pixel buffers."""

        self.inspection = inspection
        self.estimate = estimate
        self.max_memory_mb = max_memory_mb
        super().__init__(
            f"Conservative EXR memory estimate {estimate.estimated_mib:.6f} MiB exceeds "
            f"the configured budget of {max_memory_mb:.6f} MiB. "
            "This admission estimate is not a hard RSS limit."
        )


def validate_memory_budget(max_memory_mb: float) -> float:
    """Return a positive finite MiB budget, rejecting booleans and invalid numbers."""

    if isinstance(max_memory_mb, bool) or not isinstance(max_memory_mb, (int, float)):
        raise ValueError("Memory budget must be a positive finite number of MiB.")
    try:
        value = float(max_memory_mb)
    except OverflowError as exc:
        raise ValueError("Memory budget must be a positive finite number of MiB.") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Memory budget must be a positive finite number of MiB.")
    return value


def _validate_dimensions(width: int, height: int) -> None:
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("Cannot estimate memory: stored dimensions must be positive integers.")


def _validate_channels(channels: tuple[str, ...]) -> None:
    if not channels or any(not isinstance(channel, str) or not channel for channel in channels):
        raise ValueError("Cannot estimate memory: every part must contain named source channels.")
    if len(set(channels)) != len(channels):
        raise ValueError("Cannot estimate memory: source channel identities must be unique.")


def _validate_data_window(region: FileInspection | PartInspection) -> None:
    window = region.data_window
    if window is None:
        return
    if (
        not isinstance(window, tuple)
        or len(window) != 2
        or any(not isinstance(point, tuple) or len(point) != 2 for point in window)
        or any(type(value) is not int for point in window for value in point)
    ):
        raise ValueError("Cannot estimate memory: dataWindow coordinates must be integer pairs.")
    minimum, maximum = window
    if (
        maximum[0] - minimum[0] + 1 != region.width
        or maximum[1] - minimum[1] + 1 != region.height
    ):
        raise ValueError("Cannot estimate memory: stored dimensions disagree with dataWindow.")


def estimate_frame_memory(inspection: FileInspection) -> MemoryEstimate:
    """Estimate all flat parts using stored pixels, channel counts and reserves.

    No pixel arrays are loaded, channel types queried or display windows used.
    Complete per-part metadata is required for multipart files; older single
    part inspections can use their top-level dimensions and channel inventory.
    Unsupported deep structures and malformed or incomplete metadata fail
    explicitly instead of yielding a misleadingly small admission estimate.
    """

    if type(inspection.part_count) is not int or inspection.part_count <= 0:
        raise ValueError("Cannot estimate memory: part_count must be a positive integer.")
    if inspection.is_deep or any(part.is_deep for part in inspection.parts):
        raise ValueError("Cannot estimate flat memory for unsupported deep EXR data.")
    _validate_dimensions(inspection.width, inspection.height)
    _validate_channels(inspection.channels)
    _validate_data_window(inspection)
    if inspection.parts:
        if len(inspection.parts) != inspection.part_count:
            raise ValueError("Cannot estimate memory: multipart metadata has an incomplete part count.")
        if (
            any(type(part.index) is not int for part in inspection.parts)
            or {part.index for part in inspection.parts} != set(range(inspection.part_count))
        ):
            raise ValueError("Cannot estimate memory: part indexes must cover each physical part once.")
        regions: tuple[FileInspection | PartInspection, ...] = inspection.parts
    else:
        if inspection.part_count != 1:
            raise ValueError("Cannot estimate memory: multipart metadata requires every part.")
        regions = (inspection,)

    sample_count = 0
    channel_count = 0
    largest_part_pixels = 0
    for region in regions:
        _validate_dimensions(region.width, region.height)
        _validate_channels(region.channels)
        _validate_data_window(region)
        pixels = region.width * region.height
        channel_count += len(region.channels)
        sample_count += pixels * len(region.channels)
        largest_part_pixels = max(largest_part_pixels, pixels)
    if channel_count != len(inspection.channels):
        raise ValueError("Cannot estimate memory: channel inventory disagrees with the per-part headers.")

    native_bytes = sample_count * NATIVE_BYTES_PER_SAMPLE
    promotion_bytes = sample_count * HALF_PROMOTION_BYTES_PER_SAMPLE
    stack_bytes = sample_count * AOV_STACK_BYTES_PER_SAMPLE
    scratch_bytes = largest_part_pixels * SCRATCH_BYTES_PER_PIXEL
    subtotal = native_bytes + promotion_bytes + stack_bytes + scratch_bytes + FIXED_RESERVE_BYTES
    estimated_bytes = (
        subtotal * _SAFETY_NUMERATOR + _SAFETY_DENOMINATOR - 1
    ) // _SAFETY_DENOMINATOR
    try:
        estimated_mib = estimated_bytes / MIB_BYTES
    except OverflowError as exc:
        raise ValueError("Cannot estimate memory: dimensions exceed the numeric display range.") from exc
    if not math.isfinite(estimated_mib):
        raise ValueError("Cannot estimate memory: dimensions exceed the numeric display range.")
    return MemoryEstimate(
        model_version=MEMORY_MODEL_VERSION,
        part_count=inspection.part_count,
        channel_count=channel_count,
        native_channel_bytes=native_bytes,
        half_promotion_bytes=promotion_bytes,
        aov_stack_bytes=stack_bytes,
        scratch_bytes=scratch_bytes,
        fixed_reserve_bytes=FIXED_RESERVE_BYTES,
        subtotal_bytes=subtotal,
        safety_margin_bytes=estimated_bytes - subtotal,
        estimated_bytes=estimated_bytes,
        estimated_mib=estimated_mib,
        safety_factor=SAFETY_FACTOR,
    )


def enforce_memory_budget(inspection: FileInspection, max_memory_mb: float) -> MemoryEstimate:
    """Return an admissible estimate or raise with structured budget evidence.

    The supplied MiB budget is compared with the exact integer byte estimate
    using the float's integer ratio. No multiplication into overflowing floats
    or rounding through the estimate's approximate MiB display is required.
    A byte estimate exactly equal to the configured budget is permitted.
    """

    budget = validate_memory_budget(max_memory_mb)
    estimate = estimate_frame_memory(inspection)
    numerator, denominator = budget.as_integer_ratio()
    if estimate.estimated_bytes * denominator > numerator * MIB_BYTES:
        raise MemoryBudgetExceeded(inspection, estimate, budget)
    return estimate
