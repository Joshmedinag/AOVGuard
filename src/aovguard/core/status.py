"""Canonical PASS, WARNING and FAIL status calculation."""

from __future__ import annotations

from enum import StrEnum

from aovguard.core.models import AnalysisReport, Severity


class AnalysisStatus(StrEnum):
    """Canonical overall states exposed by every interface."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


def severity_counts(report: AnalysisReport) -> dict[Severity, int]:
    """Count report findings by severity."""

    return {
        severity: sum(finding.severity is severity for finding in report.findings)
        for severity in Severity
    }


def analysis_status(report: AnalysisReport) -> AnalysisStatus:
    """Derive overall status from failures and finding severities."""

    counts = severity_counts(report)
    if report.failed_frame_count or counts[Severity.ERROR]:
        return AnalysisStatus.FAIL
    if report.warnings or counts[Severity.WARNING]:
        return AnalysisStatus.WARNING
    return AnalysisStatus.PASS
