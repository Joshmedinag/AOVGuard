import pytest

from aovguard.core.models import AOVCategory
from aovguard.gui.help_text import aov_tooltip, category_tooltip


def test_aov_tooltip_explains_known_color_pass() -> None:
    tooltip = aov_tooltip(
        "beauty",
        AOVCategory.COLOR,
        ("R", "G", "B", "A"),
    )

    assert "Combined rendered image" in tooltip
    assert "Category: color" in tooltip
    assert "Channels: R, G, B, A" in tooltip


def test_aov_tooltip_explains_technical_pass_without_color_semantics() -> None:
    tooltip = aov_tooltip("Z", AOVCategory.DEPTH, ("Z",))

    assert "depth" in tooltip.casefold()
    assert "not treated as color" in tooltip


def test_unknown_aov_tooltip_remains_explicitly_uncertain() -> None:
    tooltip = aov_tooltip("renderer_custom_data", "not-a-category")

    assert "Unknown AOV" in tooltip
    assert "Category: unknown" in tooltip
    assert category_tooltip("not-a-category").startswith("Unknown AOV")


@pytest.mark.parametrize(
    ("name", "category", "expected"),
    [
        ("albedo", AOVCategory.COLOR, "Surface base color"),
        ("diffuse_direct", AOVCategory.COLOR, "Direct diffuse illumination"),
        ("diffuse_indirect", AOVCategory.COLOR, "Indirect diffuse illumination"),
        ("specular_direct", AOVCategory.COLOR, "Direct specular reflection"),
        ("specular_indirect", AOVCategory.COLOR, "Indirect specular reflection"),
        ("emission", AOVCategory.COLOR, "emissive materials"),
        ("N", AOVCategory.VECTOR, "Surface normal vector"),
        ("P", AOVCategory.VECTOR, "Three-dimensional position data"),
        ("depth_z", AOVCategory.DEPTH, "Scene depth"),
        ("character_mask", AOVCategory.MASK, "Mask or matte data"),
        ("custom_scalar", AOVCategory.SCALAR, "one numerical value per pixel"),
    ],
)
def test_aov_tooltip_explains_supported_aov_semantics(
    name: str,
    category: AOVCategory,
    expected: str,
) -> None:
    assert expected in aov_tooltip(name, category)


@pytest.mark.parametrize("category", list(AOVCategory))
def test_every_aov_category_has_contextual_help(category: AOVCategory) -> None:
    tooltip = category_tooltip(category)

    assert tooltip
    assert category.value.casefold() in tooltip.casefold()
