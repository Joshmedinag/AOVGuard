from __future__ import annotations

import json
from pathlib import Path

import pytest

from aovguard.core.models import AOVCategory
from aovguard.rules.loader import load_rule_preset
from aovguard.rules.preset_writer import _atomic_write, save_aov_category_override


def test_save_toml_category_preserves_rules_and_updates_case_insensitively(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(
        "\n".join(
            (
                'preset = "lighting"',
                "",
                "[aov_categories]",
                'RendererData = "scalar"',
                "",
                "[rules.nan_inf]",
                "enabled = true",
                'severity = "error"',
            )
        ),
        encoding="utf-8",
    )

    save_aov_category_override(path, "rendererdata", AOVCategory.MASK)

    preset = load_rule_preset(path)
    assert preset.aov_category_overrides == {"RendererData": AOVCategory.MASK}
    assert preset.rules[0].id == "nan_inf"
    assert preset.rules[0].enabled is True


def test_save_category_can_create_json_preset_and_store_ignored(tmp_path: Path) -> None:
    path = tmp_path / "studio.json"

    result = save_aov_category_override(path, "VendorPayload", "ignored")

    assert result == path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["aov_categories"] == {"VendorPayload": "ignored"}
    assert load_rule_preset(path).aov_category_overrides == {"VendorPayload": AOVCategory.IGNORED}


@pytest.mark.parametrize(
    ("name", "category", "message"),
    [
        ("", "color", "must not be empty"),
        ("custom", "unknown", "cannot be saved"),
        ("custom", "invalid", "is not a valid"),
    ],
)
def test_save_category_rejects_invalid_override(
    tmp_path: Path,
    name: str,
    category: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        save_aov_category_override(tmp_path / "rules.toml", name, category)


def test_save_category_creates_toml_and_updates_existing_json(tmp_path: Path) -> None:
    toml_path = tmp_path / "new.toml"
    save_aov_category_override(toml_path, "Crypto Object", "mask")
    assert load_rule_preset(toml_path).aov_category_overrides == {"Crypto Object": AOVCategory.MASK}

    json_path = tmp_path / "existing.json"
    json_path.write_text(
        json.dumps({"preset": "existing", "rules": {}, "aov_categories": {"Z": "depth"}}),
        encoding="utf-8",
    )
    save_aov_category_override(json_path, "roughness", AOVCategory.SCALAR)
    assert load_rule_preset(json_path).aov_category_overrides == {
        "Z": AOVCategory.DEPTH,
        "roughness": AOVCategory.SCALAR,
    }


@pytest.mark.parametrize("suffix", [".yaml", ""])
def test_save_category_rejects_unsupported_format(tmp_path: Path, suffix: str) -> None:
    with pytest.raises(ValueError, match="Unsupported rules config format"):
        save_aov_category_override(tmp_path / f"rules{suffix}", "custom", "scalar")


@pytest.mark.parametrize(
    ("suffix", "text", "message"),
    [
        (".toml", 'aov_categories = ["invalid"]\n', "object/table"),
        (".json", "[]", "top level"),
        (".json", '{"aov_categories": []}', "object/table"),
    ],
)
def test_save_category_rejects_malformed_existing_preset(
    tmp_path: Path,
    suffix: str,
    text: str,
    message: str,
) -> None:
    path = tmp_path / f"rules{suffix}"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        save_aov_category_override(path, "custom", "scalar")


def test_atomic_write_removes_temporary_file_after_replace_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "nested" / "rules.toml"

    def fail_replace(_self: Path, _target: Path) -> Path:
        raise OSError("replace denied")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replace denied"):
        _atomic_write(target, "preset = 'test'\n")

    assert not target.exists()
    assert list(target.parent.glob(".rules.toml.*.tmp")) == []
