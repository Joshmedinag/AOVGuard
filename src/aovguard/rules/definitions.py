"""Immutable validation-rule and preset definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from aovguard.core.models import AOVCategory, Severity


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """Configuration for one validation-rule invocation."""

    id: str
    enabled: bool = True
    severity: Severity = Severity.WARNING
    parameters: Mapping[str, object] = field(default_factory=dict)
    supported_aov_types: frozenset[AOVCategory] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Rule id must not be empty.")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "supported_aov_types", frozenset(self.supported_aov_types))


@dataclass(frozen=True, slots=True)
class RulePreset:
    """Named collection of rules and AOV category overrides."""

    name: str
    rules: tuple[RuleDefinition, ...]
    aov_category_overrides: Mapping[str, AOVCategory] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aov_category_overrides",
            MappingProxyType(dict(self.aov_category_overrides)),
        )
