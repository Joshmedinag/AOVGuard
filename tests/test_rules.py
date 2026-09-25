from pathlib import Path

import pytest

from aovguard.core.models import (
    AnalysisReport,
    AOVCategory,
    AOVDescriptor,
    ChannelMetricSet,
    FileInspection,
    Finding,
    MetricSet,
    Severity,
)
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.engine import execute_rules


def _report(
    *,
    metrics: dict[str, MetricSet] | None = None,
    channels: tuple[str, ...] = ("R", "G", "B"),
    aovs: tuple[AOVDescriptor, ...] | None = None,
    channel_metrics=None,
    inspections: tuple[FileInspection, ...] | None = None,
) -> AnalysisReport:
    if aovs is None:
        aovs = (
            AOVDescriptor(
                name="beauty",
                channels=("R", "G", "B"),
                category=AOVCategory.COLOR,
                category_confidence="root_rgb_channels",
            ),
        )
    path = Path("shot.1001.exr")
    if inspections is None:
        inspections = (
            FileInspection(
                path=path,
                width=1,
                height=1,
                channels=channels,
                aovs=aovs,
            ),
        )
    return AnalysisReport(
        source=Path("renders"),
        frames=(path,),
        inspections=inspections,
        metrics_by_aov=metrics or {},
        channel_metrics_by_aov=channel_metrics or {},
    )


def test_nan_inf_rule_returns_error_finding() -> None:
    report = _report(
        metrics={
            "beauty": MetricSet(
                0.0,
                float("nan"),
                float("nan"),
                pixel_count=3,
                nan_count=1,
                posinf_count=1,
                neginf_count=1,
            )
        }
    )

    findings = execute_rules(
        report,
        (
            RuleDefinition(
                id="nan_inf",
                severity=Severity.ERROR,
                supported_aov_types=frozenset({AOVCategory.COLOR}),
            ),
        ),
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "nan_inf"
    assert findings[0].metrics["nan_count"] == 1


def test_channel_rules_report_exact_channel() -> None:
    report = _report(
        metrics={"beauty": MetricSet(1.0, 0.5, 1.0, pixel_count=4)},
        channel_metrics={
            "beauty": {
                "R": ChannelMetricSet(4, 0.5, 0.5, 0.5),
                "G": ChannelMetricSet(4, 0.25, -1.0, 1.0, negative_count=1),
                "B": ChannelMetricSet(4, 0.0, 0.0, 0.0, nan_count=1),
            }
        },
    )

    findings = execute_rules(
        report,
        (
            RuleDefinition(id="nan_inf", severity=Severity.ERROR),
            RuleDefinition(id="negative_values"),
            RuleDefinition(id="constant_channel", severity=Severity.INFO),
        ),
    )

    assert {(finding.rule_id, finding.channel) for finding in findings} == {
        ("nan_inf", "B"),
        ("negative_values", "G"),
        ("constant_channel", "R"),
    }


def test_extreme_value_rule_reports_exact_channel_and_threshold() -> None:
    report = _report(
        channel_metrics={
            "beauty": {
                "beauty.R": ChannelMetricSet(2, 1.0, 0.0, 2.0),
                "beauty.G": ChannelMetricSet(
                    2,
                    1_000_001.0,
                    1.0,
                    2_000_001.0,
                ),
            }
        }
    )

    findings = execute_rules(
        report,
        (
            RuleDefinition(
                id="extreme_values",
                severity=Severity.WARNING,
                parameters={"max_absolute": 1_000_000.0},
            ),
        ),
    )

    assert len(findings) == 1
    assert findings[0].channel == "beauty.G"
    assert findings[0].metrics["max_absolute"] == 1_000_000.0


def test_empty_and_near_empty_rules_are_distinct() -> None:
    report = _report(
        metrics={
            "empty": MetricSet(0.0, 0.0, 0.0, pixel_count=10),
            "near": MetricSet(0.01, 0.0005, 0.001, pixel_count=10),
        },
        aovs=(
            AOVDescriptor("empty", ("empty.R", "empty.G", "empty.B"), AOVCategory.COLOR),
            AOVDescriptor("near", ("near.R", "near.G", "near.B"), AOVCategory.COLOR),
        ),
    )

    findings = execute_rules(
        report,
        (
            RuleDefinition(id="empty_aov"),
            RuleDefinition(id="near_empty_aov"),
        ),
    )

    assert {(finding.rule_id, finding.aov) for finding in findings} == {
        ("empty_aov", "empty"),
        ("near_empty_aov", "near"),
    }


def test_constant_channel_rule_skips_already_empty_aov() -> None:
    report = _report(
        metrics={"beauty": MetricSet(0.0, 0.0, 0.0, pixel_count=4)},
        channel_metrics={
            "beauty": {
                "R": ChannelMetricSet(4, 0.0, 0.0, 0.0),
                "G": ChannelMetricSet(4, 0.0, 0.0, 0.0),
                "B": ChannelMetricSet(4, 0.0, 0.0, 0.0),
            }
        },
    )

    findings = execute_rules(
        report,
        (
            RuleDefinition(id="empty_aov"),
            RuleDefinition(id="constant_channel"),
        ),
    )

    assert [(finding.rule_id, finding.aov) for finding in findings] == [("empty_aov", "beauty")]


def test_missing_aov_and_channel_rules_use_inspection() -> None:
    findings = execute_rules(
        _report(),
        (
            RuleDefinition(
                id="missing_aov",
                severity=Severity.ERROR,
                parameters={"required": ["beauty", "diffuse"]},
            ),
            RuleDefinition(
                id="missing_channels",
                severity=Severity.ERROR,
                parameters={"required": ["R", "G", "B", "A"]},
            ),
        ),
    )

    assert {(finding.rule_id, finding.aov, finding.channel) for finding in findings} == {
        ("missing_aov", "diffuse", None),
        ("missing_channels", None, "A"),
    }


def test_disabled_and_unsupported_type_rules_are_skipped() -> None:
    report = _report(metrics={"beauty": MetricSet(0.0, 0.0, 0.0, pixel_count=1)})

    findings = execute_rules(
        report,
        (
            RuleDefinition(id="empty_aov", enabled=False),
            RuleDefinition(
                id="empty_aov",
                supported_aov_types=frozenset({AOVCategory.DEPTH}),
            ),
        ),
    )

    assert findings == ()


def test_rule_engine_isolates_unknown_and_failing_rules() -> None:
    def failing_rule(
        report: AnalysisReport,
        definition: RuleDefinition,
    ) -> list[Finding]:
        raise RuntimeError("boom")

    findings = execute_rules(
        _report(),
        (
            RuleDefinition(id="unknown"),
            RuleDefinition(id="failing"),
        ),
        registry={"failing": failing_rule},
    )

    assert len(findings) == 2
    assert all(finding.rule_id == "rule_error" for finding in findings)
    assert "Unknown validation rule" in findings[0].message
    assert "boom" in findings[1].message


def test_invalid_rule_parameters_become_rule_error() -> None:
    findings = execute_rules(
        _report(),
        (
            RuleDefinition(
                id="missing_aov",
                parameters={"required": "diffuse"},
            ),
        ),
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "rule_error"
    assert "list of strings" in findings[0].message


def test_rule_definition_and_parameter_validation_reject_empty_values() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        RuleDefinition(id=" ")

    findings = execute_rules(
        _report(),
        (
            RuleDefinition(id="missing_aov", parameters={"required": [""]}),
            RuleDefinition(
                id="constant_channel",
                parameters={"skip_empty_aovs": "yes"},
            ),
        ),
    )

    assert len(findings) == 2
    assert all(finding.rule_id == "rule_error" for finding in findings)
    assert "empty values" in findings[0].message
    assert "boolean" in findings[1].message


def test_non_finite_numeric_rule_parameter_becomes_rule_error() -> None:
    findings = execute_rules(
        _report(metrics={"beauty": MetricSet(0.0, 0.0, 0.0, pixel_count=1)}),
        (
            RuleDefinition(
                id="empty_aov",
                parameters={"max_luminance": float("nan")},
            ),
        ),
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "rule_error"
    assert "finite, non-negative" in findings[0].message


def test_sequence_consistency_rules_report_changed_frames() -> None:
    baseline_path = Path("shot.1001.exr")
    changed_path = Path("shot.1002.exr")
    beauty = AOVDescriptor(
        "beauty",
        ("R", "G", "B"),
        AOVCategory.COLOR,
    )
    diffuse = AOVDescriptor(
        "diffuse",
        ("diffuse.R", "diffuse.G", "diffuse.B"),
        AOVCategory.COLOR,
    )
    report = _report(
        inspections=(
            FileInspection(baseline_path, 1920, 1080, ("R", "G", "B"), (beauty,)),
            FileInspection(
                changed_path,
                1280,
                720,
                ("R", "G", "B", "diffuse.R", "diffuse.G", "diffuse.B"),
                (beauty, diffuse),
            ),
        )
    )

    findings = execute_rules(
        report,
        (
            RuleDefinition(id="resolution_mismatch", severity=Severity.ERROR),
            RuleDefinition(id="aov_structure_mismatch", severity=Severity.ERROR),
        ),
    )

    assert {finding.rule_id for finding in findings} == {
        "resolution_mismatch",
        "aov_structure_mismatch",
    }
    structure = next(finding for finding in findings if finding.rule_id == "aov_structure_mismatch")
    assert structure.metrics["new_aovs"] == ["diffuse"]


def test_aov_aware_rules_skip_unsupported_categories() -> None:
    report = _report(
        metrics={
            "beauty": MetricSet(
                0.01,
                0.0005,
                0.001,
                pixel_count=4,
                nan_count=1,
            )
        },
        channel_metrics={
            "beauty": {
                "R": ChannelMetricSet(
                    4,
                    -1.0,
                    -1.0,
                    -1.0,
                    nan_count=1,
                    negative_count=4,
                )
            }
        },
    )
    depth_only = frozenset({AOVCategory.DEPTH})

    findings = execute_rules(
        report,
        (
            RuleDefinition(id="nan_inf", supported_aov_types=depth_only),
            RuleDefinition(id="negative_values", supported_aov_types=depth_only),
            RuleDefinition(id="constant_channel", supported_aov_types=depth_only),
            RuleDefinition(id="near_empty_aov", supported_aov_types=depth_only),
        ),
    )

    assert findings == ()
