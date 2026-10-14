"""Pure memory-admission tests without allocating large image buffers."""

import json
import math
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from aovguard.core.memory import (
    FIXED_RESERVE_BYTES,
    MEMORY_MODEL_VERSION,
    MIB_BYTES,
    MemoryBudgetExceeded,
    enforce_memory_budget,
    estimate_frame_memory,
    validate_memory_budget,
)
from aovguard.core.models import AOVCategory, AOVDescriptor, FileInspection, PartInspection


def _inspection(
    width: int = 1,
    height: int = 1,
    channels: tuple[str, ...] = ("R", "G", "B"),
) -> FileInspection:
    return FileInspection(Path("frame.exr"), width, height, channels, ())


def _multipart() -> FileInspection:
    parts = (
        PartInspection(0, "left", 3, 2, ("R", "G", "B"), ()),
        PartInspection(1, "right", 5, 4, ("Z", "mask"), ()),
    )
    return replace(
        _inspection(3, 2),
        part_count=2,
        channels=("[part:left]::R", "[part:left]::G", "[part:left]::B", "[part:right]::Z", "[part:right]::mask"),
        parts=parts,
    )


def test_rgb_4k_estimate_has_an_explicit_conservative_breakdown() -> None:
    pixels = 3840 * 2160

    estimate = estimate_frame_memory(_inspection(3840, 2160))

    assert estimate.model_version == MEMORY_MODEL_VERSION == "flat-working-set-v1"
    assert estimate.native_channel_bytes == pixels * 3 * 4
    assert estimate.half_promotion_bytes == pixels * 3 * 4
    assert estimate.aov_stack_bytes == pixels * 3 * 8
    assert estimate.scratch_bytes == pixels * 32
    assert estimate.fixed_reserve_bytes == 64 * MIB_BYTES
    assert estimate.subtotal_bytes == 730_660_864
    assert estimate.estimated_bytes == 913_326_080
    assert estimate.estimated_mib == pytest.approx(estimate.estimated_bytes / MIB_BYTES)
    assert estimate.safety_factor == 1.25
    assert estimate.part_count == 1 and estimate.channel_count == 3


def test_multipart_sum_uses_each_part_dimensions_and_largest_scratch_region() -> None:
    estimate = estimate_frame_memory(_multipart())
    samples = (3 * 2 * 3) + (5 * 4 * 2)

    assert estimate.part_count == 2 and estimate.channel_count == 5
    assert estimate.native_channel_bytes == samples * 4
    assert estimate.half_promotion_bytes == samples * 4
    assert estimate.aov_stack_bytes == samples * 8
    assert estimate.scratch_bytes == 5 * 4 * 32


def test_display_window_does_not_change_the_stored_pixel_estimate() -> None:
    inspection = _inspection(3, 2)
    enormous_display = replace(
        inspection,
        data_window=((10, 20), (12, 21)),
        display_window=((-1000, -1000), (999_999, 999_999)),
    )

    assert estimate_frame_memory(inspection) == estimate_frame_memory(enormous_display)


def test_all_physical_channels_count_regardless_of_semantic_category() -> None:
    channels = ("R", "G", "B", "A", "vendor.foo", "ignored.AUX", "crypto00.R", "crypto00.G")
    descriptors = (
        AOVDescriptor("beauty", ("R", "G", "B", "A"), AOVCategory.COLOR),
        AOVDescriptor("vendor", ("vendor.foo",), AOVCategory.UNKNOWN),
        AOVDescriptor("ignored", ("ignored.AUX",), AOVCategory.IGNORED),
        AOVDescriptor("crypto00", ("crypto00.R", "crypto00.G"), AOVCategory.CRYPTOMATTE),
    )
    inspection = replace(_inspection(10, 5, channels), aovs=descriptors)

    estimate = estimate_frame_memory(inspection)

    assert estimate.channel_count == 8
    assert estimate.native_channel_bytes == 10 * 5 * 8 * 4
    # Selecting a semantic view cannot reduce native channel admission.
    assert estimate == estimate_frame_memory(replace(inspection, aovs=descriptors[:1]))


def test_fixed_overhead_and_safety_margin_are_included_for_small_frames() -> None:
    estimate = estimate_frame_memory(_inspection(channels=("Z",)))

    assert estimate.subtotal_bytes == FIXED_RESERVE_BYTES + 48
    assert estimate.estimated_bytes == 80 * MIB_BYTES + 60
    assert estimate.safety_margin_bytes == estimate.estimated_bytes - estimate.subtotal_bytes
    assert estimate.estimated_bytes * 4 >= estimate.subtotal_bytes * 5
    assert (estimate.estimated_bytes - 1) * 4 < estimate.subtotal_bytes * 5


def test_large_dimensions_use_exact_python_integer_arithmetic_without_allocations() -> None:
    width, height = 2**40, 2**35

    estimate = estimate_frame_memory(_inspection(width, height))

    expected_subtotal = width * height * 80 + FIXED_RESERVE_BYTES
    assert estimate.subtotal_bytes == expected_subtotal
    assert estimate.estimated_bytes == (expected_subtotal * 5 + 3) // 4
    assert isinstance(estimate.estimated_bytes, int)


def test_estimate_is_immutable_and_can_be_serialized_with_asdict() -> None:
    estimate = estimate_frame_memory(_inspection())

    with pytest.raises(FrozenInstanceError):
        estimate.estimated_bytes = 0  # type: ignore[misc]
    payload = json.loads(json.dumps(asdict(estimate), allow_nan=False))
    assert payload["model_version"] == MEMORY_MODEL_VERSION
    assert payload["estimated_bytes"] == estimate.estimated_bytes


@pytest.mark.parametrize("width,height", [(0, 1), (1, -1), (True, 1), (1.5, 1)])
def test_invalid_stored_dimensions_cannot_produce_an_estimate(width, height) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        estimate_frame_memory(_inspection(width, height))


@pytest.mark.parametrize("channels", [(), ("",), ("R", "R"), ("R", 1)])
def test_empty_malformed_or_duplicate_channels_are_rejected(channels) -> None:
    with pytest.raises(ValueError, match="channel"):
        estimate_frame_memory(_inspection(channels=channels))


@pytest.mark.parametrize("part_count", [0, -1, True, 1.5])
def test_invalid_part_counts_are_rejected(part_count) -> None:
    with pytest.raises(ValueError, match="part_count"):
        estimate_frame_memory(replace(_inspection(), part_count=part_count))


def test_multipart_without_complete_metadata_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires every part"):
        estimate_frame_memory(replace(_inspection(), part_count=2))
    with pytest.raises(ValueError, match="incomplete part count"):
        estimate_frame_memory(replace(_multipart(), parts=_multipart().parts[:1]))
    with pytest.raises(ValueError, match="incomplete part count"):
        estimate_frame_memory(replace(_multipart(), part_count=1))


def test_duplicate_or_out_of_range_part_indexes_are_rejected() -> None:
    inspection = _multipart()
    with pytest.raises(ValueError, match="part indexes"):
        estimate_frame_memory(replace(
            inspection, parts=(inspection.parts[0], replace(inspection.parts[1], index=0)),
        ))


def test_per_part_channels_and_aggregate_inventory_must_agree() -> None:
    inspection = _multipart()
    with pytest.raises(ValueError, match="channel inventory"):
        estimate_frame_memory(replace(inspection, channels=inspection.channels[:-1]))
    with pytest.raises(ValueError, match="named source channels"):
        estimate_frame_memory(replace(
            inspection, parts=(inspection.parts[0], replace(inspection.parts[1], channels=())),
        ))


def test_invalid_per_part_dimensions_are_rejected() -> None:
    inspection = _multipart()
    with pytest.raises(ValueError, match="dimensions"):
        estimate_frame_memory(replace(
            inspection, parts=(inspection.parts[0], replace(inspection.parts[1], width=0)),
        ))


def test_inconsistent_or_malformed_data_windows_are_rejected() -> None:
    with pytest.raises(ValueError, match="disagree with dataWindow"):
        estimate_frame_memory(replace(_inspection(3, 2), data_window=((0, 0), (3, 1))))
    with pytest.raises(ValueError, match="integer pairs"):
        estimate_frame_memory(replace(_inspection(3, 2), data_window=((0, 0), (2, 1.0))))


def test_deep_data_cannot_use_the_flat_memory_model() -> None:
    with pytest.raises(ValueError, match="deep EXR"):
        estimate_frame_memory(replace(_inspection(), is_deep=True))
    inspection = _multipart()
    with pytest.raises(ValueError, match="deep EXR"):
        estimate_frame_memory(replace(
            inspection, parts=(inspection.parts[0], replace(inspection.parts[1], is_deep=True)),
        ))


def test_unrepresentable_display_estimate_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="numeric display range"):
        estimate_frame_memory(_inspection(10**400, 1))


def test_equal_admission_budget_is_allowed_and_just_lower_budget_is_rejected() -> None:
    inspection = _inspection()
    estimate = estimate_frame_memory(inspection)

    assert enforce_memory_budget(inspection, estimate.estimated_mib) == estimate
    with pytest.raises(MemoryBudgetExceeded) as error:
        enforce_memory_budget(inspection, math.nextafter(estimate.estimated_mib, 0.0))
    assert error.value.inspection is inspection
    assert error.value.estimate == estimate
    assert error.value.max_memory_mb < estimate.estimated_mib
    assert "not a hard RSS limit" in str(error.value)


def test_huge_finite_budget_does_not_overflow_when_converted_to_bytes() -> None:
    estimate = enforce_memory_budget(_inspection(), 1e308)

    assert estimate.estimated_bytes > 0


def test_budget_comparison_uses_exact_bytes_instead_of_rounded_mib() -> None:
    # This estimate is larger than a float's exact integer mantissa. Choose
    # stored pixels so that the rounded MiB value falls just below its bytes.
    inspection = _inspection(2**55 + 1, 1, channels=("Z",))
    estimate = estimate_frame_memory(inspection)
    numerator, denominator = estimate.estimated_mib.as_integer_ratio()
    assert estimate.estimated_bytes * denominator > numerator * MIB_BYTES

    with pytest.raises(MemoryBudgetExceeded):
        enforce_memory_budget(inspection, estimate.estimated_mib)


@pytest.mark.parametrize("budget", [0, -1, True, None, "128", float("nan"), float("inf"), 10**400])
def test_public_budget_helpers_reject_invalid_values(budget) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        validate_memory_budget(budget)
    with pytest.raises(ValueError, match="positive finite"):
        enforce_memory_budget(_inspection(), budget)
