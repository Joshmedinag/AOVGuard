from pathlib import Path

import pytest

from aovguard.core.models import AnalysisReport, Finding, Severity
from aovguard.core.status import AnalysisStatus, analysis_status, severity_counts


def _report(
    *,
    findings: tuple[Finding, ...] = (),
    warnings: tuple[str, ...] = (),
    failed_frames: tuple[Path, ...] = (),
) -> AnalysisReport:
    return AnalysisReport(
        source=Path("renders"),
        frames=failed_frames,
        inspections=(),
        metrics_by_aov={},
        successful_frames=(),
        failed_frames=failed_frames,
        findings=findings,
        warnings=warnings,
    )


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (_report(), AnalysisStatus.PASS),
        (_report(warnings=("Mixed input",)), AnalysisStatus.WARNING),
        (
            _report(
                findings=(Finding("empty", Severity.WARNING, "Empty AOV"),),
            ),
            AnalysisStatus.WARNING,
        ),
        (
            _report(
                findings=(Finding("nan_inf", Severity.ERROR, "Invalid values"),),
            ),
            AnalysisStatus.FAIL,
        ),
        (_report(failed_frames=(Path("broken.exr"),)), AnalysisStatus.FAIL),
    ],
)
def test_analysis_status(report: AnalysisReport, expected: AnalysisStatus) -> None:
    assert analysis_status(report) is expected


def test_severity_counts_includes_zero_values() -> None:
    report = _report(
        findings=(Finding("constant", Severity.INFO, "Constant channel"),),
    )

    assert severity_counts(report) == {
        Severity.INFO: 1,
        Severity.WARNING: 0,
        Severity.ERROR: 0,
    }
