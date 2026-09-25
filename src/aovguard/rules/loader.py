"""TOML and JSON rule-preset loading and validation."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from aovguard.core.models import AOVCategory, Severity
from aovguard.rules.definitions import RuleDefinition, RulePreset


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Rules config does not exist: {path}")
    if path.suffix.lower() == ".toml":
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    elif path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError("Unsupported rules config format. Use .toml or .json")
    if not isinstance(data, dict):
        raise ValueError("Rules config must contain an object at the top level.")
    return data


def _severity(value: object) -> Severity:
    try:
        return Severity(str(value).lower())
    except ValueError as exc:
        valid = ", ".join(severity.value for severity in Severity)
        raise ValueError(f"Invalid rule severity {value!r}. Expected one of: {valid}") from exc


def _categories(value: object) -> frozenset[AOVCategory]:
    if value is None:
        return frozenset()
    if isinstance(value, str) or not isinstance(value, list):
        raise ValueError("supported_aov_types must be a list of category names.")
    try:
        return frozenset(AOVCategory(str(item).lower()) for item in value)
    except ValueError as exc:
        valid = ", ".join(category.value for category in AOVCategory)
        raise ValueError(f"Invalid AOV category. Expected one of: {valid}") from exc


def _category_overrides(value: object) -> dict[str, AOVCategory]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("aov_categories must be an object/table of AOV names and categories.")
    overrides: dict[str, AOVCategory] = {}
    for name, category in value.items():
        aov_name = str(name).strip()
        if not aov_name:
            raise ValueError("aov_categories must not contain an empty AOV name.")
        try:
            resolved = AOVCategory(str(category).lower())
        except ValueError as exc:
            valid = ", ".join(item.value for item in AOVCategory)
            raise ValueError(
                f"Invalid category override for AOV {aov_name!r}. Expected one of: {valid}"
            ) from exc
        if resolved is AOVCategory.UNKNOWN:
            raise ValueError(f"Category override for AOV {aov_name!r} must be a known category.")
        overrides[aov_name] = resolved
    return overrides


def load_rule_preset(path: str | Path) -> RulePreset:
    """Load and validate a TOML or JSON rule preset."""

    config_path = Path(path)
    data = _read_config(config_path)
    preset_name = str(data.get("preset", config_path.stem))
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, dict):
        raise ValueError("Rules config must contain a 'rules' object/table.")

    definitions: list[RuleDefinition] = []
    for rule_id, raw_definition in raw_rules.items():
        if not isinstance(raw_definition, dict):
            raise ValueError(f"Rule {rule_id!r} must contain an object/table.")
        known_fields = {
            "enabled",
            "severity",
            "parameters",
            "supported_aov_types",
        }
        unknown = sorted(set(raw_definition) - known_fields)
        if unknown:
            raise ValueError(f"Rule {rule_id!r} has unknown field(s): {', '.join(unknown)}")

        parameters = raw_definition.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError(f"Rule {rule_id!r} parameters must be an object/table.")
        enabled = raw_definition.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"Rule {rule_id!r} enabled must be a boolean.")

        definitions.append(
            RuleDefinition(
                id=str(rule_id),
                enabled=enabled,
                severity=_severity(raw_definition.get("severity", Severity.WARNING.value)),
                parameters=parameters,
                supported_aov_types=_categories(raw_definition.get("supported_aov_types")),
            )
        )

    return RulePreset(
        name=preset_name,
        rules=tuple(definitions),
        aov_category_overrides=_category_overrides(data.get("aov_categories")),
    )
