"""Rule dispatch for enabled validation definitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from aovguard.core.models import AnalysisReport, Finding, Severity
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.registry import RULES, RuleFunction


def execute_rules(
    report: AnalysisReport,
    definitions: Sequence[RuleDefinition],
    *,
    registry: Mapping[str, RuleFunction] = RULES,
) -> tuple[Finding, ...]:
    """Execute enabled rules while isolating failures per rule."""

    findings: list[Finding] = []
    for definition in definitions:
        if not definition.enabled:
            continue

        rule = registry.get(definition.id)
        if rule is None:
            findings.append(
                Finding(
                    rule_id="rule_error",
                    severity=Severity.ERROR,
                    message=f"Unknown validation rule: {definition.id}",
                    file=report.source,
                    metrics={"failed_rule_id": definition.id},
                )
            )
            continue

        try:
            findings.extend(rule(report, definition))
        except Exception as exc:
            findings.append(
                Finding(
                    rule_id="rule_error",
                    severity=Severity.ERROR,
                    message=f"Rule {definition.id!r} failed: {exc}",
                    file=report.source,
                    metrics={
                        "failed_rule_id": definition.id,
                        "exception_type": type(exc).__name__,
                    },
                )
            )
    return tuple(findings)
