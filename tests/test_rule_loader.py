import json
from pathlib import Path

import pytest

from aovguard.core.models import AOVCategory, Severity
from aovguard.rules.loader import load_rule_preset


def test_load_rule_preset_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "lighting.toml"
    path.write_text(
        "\n".join(
            [
                'preset = "lighting_delivery"',
                "[rules.nan_inf]",
                "enabled = true",
                'severity = "error"',
                'supported_aov_types = ["color"]',
                "[rules.empty_aov]",
                "enabled = false",
                "[rules.empty_aov.parameters]",
                "max_luminance = 0.01",
            ]
        )
    )

    preset = load_rule_preset(path)

    assert preset.name == "lighting_delivery"
    assert [rule.id for rule in preset.rules] == ["nan_inf", "empty_aov"]
    assert preset.rules[0].severity is Severity.ERROR
    assert preset.rules[0].supported_aov_types == frozenset({AOVCategory.COLOR})
    assert preset.rules[1].enabled is False
    assert preset.rules[1].parameters["max_luminance"] == 0.01


def test_load_rule_preset_from_json(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "preset": "json_preset",
                "aov_categories": {"rendererData": "scalar"},
                "rules": {
                    "missing_aov": {
                        "severity": "warning",
                        "parameters": {"required": ["diffuse", "specular"]},
                    }
                },
            }
        )
    )

    preset = load_rule_preset(path)

    assert preset.name == "json_preset"
    assert preset.rules[0].parameters["required"] == ["diffuse", "specular"]
    assert preset.aov_category_overrides == {
        "rendererData": AOVCategory.SCALAR,
    }


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"rules": []}', "'rules' object"),
        ('{"rules": {"nan_inf": {"severity": "fatal"}}}', "Invalid rule severity"),
        ('{"rules": {"nan_inf": {"supported_aov_types": ["invalid"]}}}', "Invalid AOV category"),
        ('{"rules": {"nan_inf": {"unexpected": true}}}', "unknown field"),
        ('{"rules": {"nan_inf": {"parameters": []}}}', "parameters must be an object"),
        ('{"rules": {"nan_inf": {"enabled": "false"}}}', "enabled must be a boolean"),
        ('{"rules": {}, "aov_categories": []}', "aov_categories must be an object"),
        ('{"rules": {}, "aov_categories": {"custom": "invalid"}}', "Invalid category override"),
        ('{"rules": {}, "aov_categories": {"custom": "unknown"}}', "must be a known category"),
    ],
)
def test_load_rule_preset_rejects_invalid_config(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(content)

    with pytest.raises(ValueError, match=message):
        load_rule_preset(path)


def test_load_rule_preset_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("rules: {}")

    with pytest.raises(ValueError, match="Unsupported"):
        load_rule_preset(path)


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("top-level.json", "[]", "top level"),
        (
            "category.json",
            '{"rules":{"nan_inf":{"supported_aov_types":"color"}}}',
            "must be a list",
        ),
        ("definition.json", '{"rules":{"nan_inf":true}}', "must contain an object"),
    ],
)
def test_load_rule_preset_rejects_additional_invalid_shapes(
    tmp_path: Path,
    filename: str,
    content: str,
    message: str,
) -> None:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_rule_preset(path)


def test_load_rule_preset_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        load_rule_preset(tmp_path / "missing.toml")
