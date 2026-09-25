"""Registry mapping built-in rule identifiers to validators."""

from __future__ import annotations

from collections.abc import Callable

from aovguard.core.models import AnalysisReport, Finding
from aovguard.rules.builtin import (
    validate_aov_structure_mismatch,
    validate_constant_channel,
    validate_empty_aov,
    validate_extreme_values,
    validate_missing_aov,
    validate_missing_channels,
    validate_nan_inf,
    validate_near_empty_aov,
    validate_negative_values,
    validate_resolution_mismatch,
    validate_unknown_aov,
)
from aovguard.rules.definitions import RuleDefinition

RuleFunction = Callable[[AnalysisReport, RuleDefinition], list[Finding]]

RULES: dict[str, RuleFunction] = {
    "unknown_aov": validate_unknown_aov,
    "nan_inf": validate_nan_inf,
    "empty_aov": validate_empty_aov,
    "near_empty_aov": validate_near_empty_aov,
    "missing_aov": validate_missing_aov,
    "missing_channels": validate_missing_channels,
    "negative_values": validate_negative_values,
    "extreme_values": validate_extreme_values,
    "constant_channel": validate_constant_channel,
    "resolution_mismatch": validate_resolution_mismatch,
    "aov_structure_mismatch": validate_aov_structure_mismatch,
}
