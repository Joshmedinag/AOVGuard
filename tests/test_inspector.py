from pathlib import Path

import pytest

from aovguard.core.models import AOVCategory
from aovguard.io.inspector import (
    build_file_inspection,
    infer_aov_descriptor,
    infer_aov_descriptors,
)


def _by_name(descriptors):
    return {descriptor.name: descriptor for descriptor in descriptors}


def test_infer_aov_descriptors_detects_root_rgba_as_beauty() -> None:
    descriptors = infer_aov_descriptors(("R", "G", "B", "A"))

    beauty = descriptors[0]
    assert beauty.name == "beauty"
    assert beauty.channels == ("R", "G", "B", "A")
    assert beauty.category is AOVCategory.COLOR
    assert beauty.category_confidence == "root_rgb_channels"


def test_infer_aov_descriptors_detects_named_rgb_aovs() -> None:
    descriptors = _by_name(
        infer_aov_descriptors(
            (
                "diffuse.R",
                "diffuse.G",
                "diffuse.B",
                "specular.red",
                "specular.green",
                "specular.blue",
            )
        )
    )

    assert descriptors["diffuse"].category is AOVCategory.COLOR
    assert descriptors["diffuse"].category_confidence == "rgb_channels"
    assert descriptors["specular"].category is AOVCategory.COLOR


def test_infer_aov_descriptors_detects_lowercase_root_rgb() -> None:
    descriptors = infer_aov_descriptors(("r", "g", "b"))

    assert descriptors[0].name == "beauty"
    assert descriptors[0].channels == ("r", "g", "b")
    assert descriptors[0].category is AOVCategory.COLOR


def test_infer_aov_descriptors_detects_depth_vector_and_mask_channels() -> None:
    descriptors = _by_name(
        infer_aov_descriptors(
            (
                "R",
                "G",
                "B",
                "Z",
                "N.X",
                "N.Y",
                "N.Z",
                "P.X",
                "P.Y",
                "P.Z",
                "shadow_matte",
            )
        )
    )

    assert descriptors["beauty"].category is AOVCategory.COLOR
    assert descriptors["Z"].category is AOVCategory.DEPTH
    assert descriptors["N"].category is AOVCategory.VECTOR
    assert descriptors["N"].category_confidence == "known_vector_name"
    assert descriptors["P"].category is AOVCategory.VECTOR
    assert descriptors["shadow_matte"].category is AOVCategory.MASK


def test_infer_aov_descriptors_prioritizes_known_arnold_technical_aovs() -> None:
    descriptors = _by_name(
        infer_aov_descriptors(
            (
                "N.R",
                "N.G",
                "N.B",
                "P.R",
                "P.G",
                "P.B",
                "Z.R",
                "Z.G",
                "Z.B",
            )
        )
    )

    assert descriptors["N"].category is AOVCategory.VECTOR
    assert descriptors["N"].category_confidence == "known_vector_name"
    assert descriptors["P"].category is AOVCategory.VECTOR
    assert descriptors["Z"].category is AOVCategory.DEPTH
    assert descriptors["Z"].category_confidence == "known_depth_name"


def test_infer_aov_descriptor_marks_incomplete_rgb_group_as_unknown() -> None:
    descriptor = infer_aov_descriptor("diffuse", ("diffuse.R", "diffuse.G"))

    assert descriptor.category is AOVCategory.UNKNOWN
    assert descriptor.category_confidence == "insufficient_evidence"


def test_infer_aov_descriptor_marks_single_root_custom_channel_as_scalar() -> None:
    descriptor = infer_aov_descriptor("object_id", ("object_id",))

    assert descriptor.category is AOVCategory.SCALAR
    assert descriptor.category_confidence == "single_root_channel"


def test_infer_aov_descriptor_uses_structure_for_custom_vector_and_named_scalar() -> None:
    vector = infer_aov_descriptor(
        "custom_direction",
        ("custom_direction.X", "custom_direction.Y", "custom_direction.Z"),
    )
    depth = infer_aov_descriptor("custom", ("custom.depth",))
    mask = infer_aov_descriptor("custom", ("custom.mask",))

    assert vector.category is AOVCategory.VECTOR
    assert vector.category_confidence == "xyz_channels"
    assert depth.category is AOVCategory.DEPTH
    assert mask.category is AOVCategory.MASK


def test_build_file_inspection_returns_structured_model() -> None:
    inspection = build_file_inspection(
        path=Path("shot.1001.exr"),
        width=1920,
        height=1080,
        channels=("R", "G", "B", "diffuse.R", "diffuse.G", "diffuse.B"),
        warnings=("test warning",),
    )

    assert inspection.path == Path("shot.1001.exr")
    assert inspection.width == 1920
    assert inspection.height == 1080
    assert inspection.channels == ("R", "G", "B", "diffuse.R", "diffuse.G", "diffuse.B")
    assert inspection.warnings == ("test warning",)
    assert [aov.name for aov in inspection.aovs] == ["beauty", "diffuse"]


def test_build_file_inspection_rejects_invalid_metadata() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        build_file_inspection(path="bad.exr", width=0, height=1, channels=("R", "G", "B"))

    with pytest.raises(ValueError, match="part_count"):
        build_file_inspection(
            path="bad.exr",
            width=1,
            height=1,
            channels=("R", "G", "B"),
            part_count=0,
        )
