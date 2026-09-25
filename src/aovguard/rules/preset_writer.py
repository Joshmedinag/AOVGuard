"""Atomic persistence of user-confirmed AOV category overrides."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from aovguard.core.models import AOVCategory


def _validated_category(category: AOVCategory | str) -> AOVCategory:
    resolved = category if isinstance(category, AOVCategory) else AOVCategory(str(category).lower())
    if resolved is AOVCategory.UNKNOWN:
        raise ValueError("Unknown is an inferred state and cannot be saved as an override.")
    return resolved


def _updated_categories(
    current: object,
    aov_name: str,
    category: AOVCategory,
) -> dict[str, str]:
    if current is None:
        values: dict[str, str] = {}
    elif isinstance(current, dict):
        values = {str(name): str(value) for name, value in current.items()}
    else:
        raise ValueError("aov_categories must be an object/table before it can be updated.")

    existing = next(
        (name for name in values if name.casefold() == aov_name.casefold()),
        None,
    )
    values[existing or aov_name] = category.value
    return dict(sorted(values.items(), key=lambda item: item[0].casefold()))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _toml_key(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _save_toml(
    path: Path,
    aov_name: str,
    category: AOVCategory,
) -> None:
    if path.exists():
        raw = path.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
        text = raw.decode("utf-8")
    else:
        data = {"preset": path.stem, "rules": {}}
        text = f"preset = {_toml_key(path.stem)}\n\n[rules]\n"

    categories = _updated_categories(data.get("aov_categories"), aov_name, category)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    section_start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.split("#", 1)[0].strip().casefold() == "[aov_categories]"
        ),
        None,
    )
    category_lines = [
        f"{_toml_key(name)} = {_toml_key(value)}{newline}" for name, value in categories.items()
    ]
    if section_start is None:
        insertion = next(
            (
                index
                for index, line in enumerate(lines)
                if line.lstrip().casefold().startswith("[rules")
            ),
            len(lines),
        )
        block = [f"[aov_categories]{newline}", *category_lines, newline]
        lines[insertion:insertion] = block
    else:
        section_end = next(
            (
                index
                for index in range(section_start + 1, len(lines))
                if lines[index].lstrip().startswith("[")
            ),
            len(lines),
        )
        lines[section_start + 1 : section_end] = [*category_lines, newline]
    _atomic_write(path, "".join(lines))


def _save_json(
    path: Path,
    aov_name: str,
    category: AOVCategory,
) -> None:
    if path.exists():
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Rules config must contain an object at the top level.")
    else:
        data = {"preset": path.stem, "rules": {}}
    data["aov_categories"] = _updated_categories(
        data.get("aov_categories"),
        aov_name,
        category,
    )
    _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def save_aov_category_override(
    path: str | Path,
    aov_name: str,
    category: AOVCategory | str,
) -> Path:
    """Persist one confirmed AOV category override in a TOML or JSON preset.

    Existing rule definitions remain unchanged. Matching AOV names are updated
    case-insensitively so a preset cannot accumulate ambiguous duplicates.
    """

    preset_path = Path(path)
    name = str(aov_name).strip()
    if not name:
        raise ValueError("AOV name must not be empty.")
    resolved = _validated_category(category)
    suffix = preset_path.suffix.casefold()
    if suffix == ".toml":
        _save_toml(preset_path, name, resolved)
    elif suffix == ".json":
        _save_json(preset_path, name, resolved)
    else:
        raise ValueError("Unsupported rules config format. Use .toml or .json")
    return preset_path
