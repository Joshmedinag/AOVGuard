"""Configuration loading for the legacy threshold-based analyzers."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from aovguard.analysis_core import Thresholds


def _read_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")

    suffix = path.suffix.lower()
    if suffix == ".toml":
        with path.open("rb") as f:
            return tomllib.load(f)
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("JSON config must contain an object at the top level.")
            return data

    raise ValueError("Unsupported config format. Use .toml or .json")


def load_thresholds(path: str | Path | None) -> Thresholds:
    """Load analysis thresholds from a TOML or JSON config file.

    Accepted layouts:
    - {"analysis": {"empty_max_luminance": ...}}
    - {"thresholds": {"empty_max_luminance": ...}}
    - {"empty_max_luminance": ...}
    """

    if path is None:
        return Thresholds()

    data = _read_config(path)
    values = data.get("analysis", data.get("thresholds", data))
    if not isinstance(values, dict):
        raise ValueError("Config thresholds must be a dictionary.")

    valid_fields = set(Thresholds.__dataclass_fields__)
    unknown = sorted(set(values) - valid_fields)
    if unknown:
        raise ValueError(f"Unknown threshold field(s): {', '.join(unknown)}")

    return Thresholds(**{key: float(value) for key, value in values.items()})


def merge_threshold_overrides(
    base: Thresholds,
    *,
    empty_max_luminance: float | None = None,
    empty_max_average: float | None = None,
    nearly_empty_max_ratio: float | None = None,
    nearly_empty_max_average: float | None = None,
    review_max_ratio: float | None = None,
    review_max_average: float | None = None,
) -> Thresholds:
    """Return a copy of *base* with optional CLI/UI overrides applied."""

    values = base.as_dict()
    overrides = {
        "empty_max_luminance": empty_max_luminance,
        "empty_max_average": empty_max_average,
        "nearly_empty_max_ratio": nearly_empty_max_ratio,
        "nearly_empty_max_average": nearly_empty_max_average,
        "review_max_ratio": review_max_ratio,
        "review_max_average": review_max_average,
    }
    for key, value in overrides.items():
        if value is not None:
            values[key] = float(value)
    return Thresholds(**values)
