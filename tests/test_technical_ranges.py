"""Technical range contracts preserve exact frame evidence and baseline semantics."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import OpenEXR
import pytest

from aovguard import cli
from aovguard.core.analysis import analyze
from aovguard.core.findings import finding_recommendation
from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    AOVCategory,
    AOVDescriptor,
    ChannelMetricSet,
    FileInspection,
    Severity,
)
from aovguard.io.reader import OpenEXRReader
from aovguard.reports.comparison import compare_report_payloads
from aovguard.reports.html_report import build_analysis_html
from aovguard.reports.json_report import build_analysis_report_payload
from aovguard.rules.builtin import default_rule_definitions, effective_rule_parameters
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.engine import execute_rules
from aovguard.rules.loader import load_rule_preset


def _rule(ranges=None, **kwargs):
    return RuleDefinition(
        "technical_range",
        parameters={"ranges": ranges if ranges is not None else {"Z": {"min": 0}}},
        **kwargs,
    )


def _report(values, *, name="Z", category=AOVCategory.DEPTH, channels=("Z",)):
    paths = tuple(Path(f"shot.{index:04d}.exr") for index in range(1, len(values) + 1))
    return AnalysisReport(
        source=Path("renders"),
        frames=paths,
        metrics_by_aov={},
        inspections=tuple(
            FileInspection(path, 2, 1, channels, (AOVDescriptor(name, channels, category),))
            for path in paths
        ),
        frame_channel_metrics={
            path: {name: {channel: metric for channel in channels}}
            for path, metric in zip(paths, values, strict=True)
        },
    )


def _metric(low, high, **kwargs):
    return ChannelMetricSet(
        pixel_count=2, avg_value=(low + high) / 2, min_value=low, max_value=high, **kwargs
    )


@pytest.mark.parametrize(
    "category", [AOVCategory.DEPTH, AOVCategory.MASK, AOVCategory.SCALAR, AOVCategory.VECTOR]
)
def test_all_technical_components_are_checked_and_only_bad_frames_are_attributed(category):
    report = _report(
        [_metric(0, 1), _metric(-0.25, 1.5), _metric(-0.5, 1)],
        category=category,
        channels=("Z.R", "Z.G", "Z.B", "Z.A"),
    )
    findings = execute_rules(report, (_rule({"Z": {"min": 0, "max": 1}}, severity=Severity.ERROR),))
    assert {finding.channel for finding in findings} == {"Z.R", "Z.G", "Z.B", "Z.A"}
    for finding in findings:
        assert finding.file is None
        assert finding.affected_files == report.frames[1:]
        assert finding.severity is Severity.ERROR
        assert finding.metrics["expected_min"] == 0.0
        assert finding.metrics["expected_max"] == 1.0
        assert finding.metrics["affected_frame_count"] == 2
        assert set(finding.metrics["per_frame"]) == {str(path) for path in report.frames[1:]}
        assert finding.metrics["per_frame"][str(report.frames[1])]["min_value"] == -0.25
        assert "units" in finding_recommendation(finding)


@pytest.mark.parametrize(
    "bounds,low,high",
    [
        ({"min": 0, "max": 1}, 0, 1),
        ({"min": 0, "max": 1, "tolerance": 0.125}, -0.125, 1.125),
        ({"min": -1, "max": 1}, -1, 1),
        ({"min": 0}, 0, 1e30),
        ({"max": 0}, -1e30, 0),
        ({"min": 0, "max": 0}, 0, 0),
    ],
)
def test_range_bounds_are_inclusive_signed_and_can_be_one_sided(bounds, low, high):
    assert execute_rules(_report([_metric(low, high)]), (_rule({"Z": bounds}),)) == ()


def test_single_violation_has_exact_file_and_does_not_invent_pixel_count():
    report = _report([_metric(-0.126, 1)])
    (finding,) = execute_rules(report, (_rule({"Z": {"min": 0, "tolerance": 0.125}}),))
    assert finding.file == report.frames[0]
    assert finding.metrics["expected_max"] is None
    assert "out_of_range_count" not in finding.metrics


def test_nonfinite_only_channels_are_left_to_integrity_rule():
    nonfinite = _metric(float("nan"), float("nan"), nan_count=1, posinf_count=1)
    assert execute_rules(_report([nonfinite]), (_rule(),)) == ()
    assert execute_rules(_report([replace(nonfinite, pixel_count=0)]), (_rule(),)) == ()
    mixed = _metric(-2, -2, nan_count=1)
    (finding,) = execute_rules(_report([mixed]), (_rule(),))
    assert next(iter(finding.metrics["per_frame"].values()))["finite_count"] == 1


@pytest.mark.parametrize(
    "ranges",
    [
        {},
        [],
        "Z",
        {"": {"min": 0}},
        {" ": {"min": 0}},
        {1: {"min": 0}},
        {"Z": []},
        {"Z": {}},
        {"Z": {"tolerance": 0}},
        {"Z": {"minimum": 0}},
        {"Z": {"min": True}},
        {"Z": {"min": "0"}},
        {"Z": {"min": None}},
        {"Z": {"max": float("inf")}},
        {"Z": {"min": float("nan")}},
        {"Z": {"min": 10**400}},
        {"Z": {"min": 2, "max": 1}},
        {"Z": {"min": 0, "tolerance": -0.01}},
        {"Z": {"min": 0, "tolerance": True}},
        {"Z": {"min": -1e308, "tolerance": 1e308}},
        {"Z": {"max": 1e308, "tolerance": 1e308}},
    ],
)
def test_invalid_policies_become_rule_errors_instead_of_silent_passes(ranges):
    (finding,) = execute_rules(_report([_metric(1, 2)]), (_rule(ranges),))
    assert finding.rule_id == "rule_error"
    assert finding.severity is Severity.ERROR
    assert finding.metrics["failed_rule_id"] == "technical_range"


def test_unknown_parameter_and_missing_policy_are_reported():
    report = _report([_metric(0, 1)])
    for parameters in ({}, {"range": {"Z": {"min": 0}}}):
        definition = RuleDefinition("technical_range", parameters=parameters)
        (finding,) = execute_rules(report, (definition,))
        assert finding.rule_id == "rule_error"
        assert effective_rule_parameters(definition) == parameters


@pytest.mark.parametrize(
    "category",
    [AOVCategory.CRYPTOMATTE, AOVCategory.UNKNOWN, AOVCategory.IGNORED, AOVCategory.COLOR],
)
def test_range_policy_rejects_non_technical_categories(category):
    report = _report([_metric(-1e30, 1e30)], category=category)
    (finding,) = execute_rules(report, (_rule(),))
    assert finding.rule_id == "rule_error"
    assert "expected depth, mask, scalar or vector" in finding.message
    assert report.frame_channel_metrics[report.frames[0]]["Z"]["Z"].min_value == -1e30


def test_categories_are_checked_per_frame_not_only_on_first_inspection():
    report = _report([_metric(0, 1), _metric(-1e30, 1e30)])
    report = replace(
        report,
        inspections=(
            report.inspections[0],
            replace(
                report.inspections[1], aovs=(AOVDescriptor("Z", ("Z",), AOVCategory.CRYPTOMATTE),)
            ),
        ),
    )
    (finding,) = execute_rules(report, (_rule(),))
    assert finding.rule_id == "rule_error"
    assert str(report.frames[1]) in finding.message


def test_missing_and_multipart_targets_are_matched_exactly():
    name = "[part:left]::Z"
    report = _report([_metric(-1, 2)], name=name, channels=(f"{name}.R",))
    for wrong_name in ("Z", "[part:right]::Z", "[part:left]::z", "*"):
        (finding,) = execute_rules(report, (_rule({wrong_name: {"min": 0}}),))
        assert finding.rule_id == "rule_error"
        assert "exactly matches" in finding.message
    (finding,) = execute_rules(report, (_rule({name: {"min": 0}}),))
    assert finding.aov == name
    assert finding.channel == f"{name}.R"


def test_category_filter_disabled_rule_and_missing_metadata():
    report = _report([_metric(-1, 0)])
    assert execute_rules(report, (_rule(supported_aov_types={AOVCategory.MASK}),)) == ()
    assert execute_rules(report, (_rule(enabled=False),)) == ()
    metadata_gap = replace(
        report,
        frame_channel_metrics={Path("other.exr"): report.frame_channel_metrics[report.frames[0]]},
    )
    (finding,) = execute_rules(metadata_gap, (_rule(),))
    assert finding.rule_id == "rule_error"
    assert "Missing inspection" in finding.message


def test_unselected_aovs_are_unchanged_and_bad_policies_cannot_partially_succeed():
    report = _report([_metric(-1, 0)])
    metrics = report.frame_channel_metrics[report.frames[0]]
    report = replace(
        report,
        frame_channel_metrics={
            report.frames[0]: {**metrics, "crypto": {"crypto.R": _metric(-1e30, 1e30)}}
        },
    )
    assert len(execute_rules(report, (_rule(),))) == 1
    (finding,) = execute_rules(report, (_rule({"Z": {"min": 0}, "invalid": {}}),))
    assert finding.rule_id == "rule_error"


def test_effective_policy_is_normalized_and_new_default_does_not_break_old_baselines():
    definition = _rule()
    assert effective_rule_parameters(definition) == {
        "ranges": {"Z": {"min": 0.0, "tolerance": 0.0}}
    }
    default = next(rule for rule in default_rule_definitions() if rule.id == definition.id)
    assert not default.enabled
    payload = build_analysis_report_payload(_report([_metric(0, 1)]), options=AnalysisOptions())
    payload["metadata"]["effective_rules"] = []
    candidate = json.loads(json.dumps(payload))
    candidate["metadata"]["effective_rules"] = [
        {
            "id": default.id,
            "enabled": False,
            "parameters": {},
        }
    ]
    assert compare_report_payloads(payload, candidate).new_findings == ()
    candidate["metadata"]["effective_rules"][0]["enabled"] = True
    with pytest.raises(ValueError, match="effective_rules"):
        compare_report_payloads(payload, candidate)


def _preset_file(tmp_path):
    path = tmp_path / "ranges.toml"
    path.write_text(
        """preset = "technical_delivery"
[aov_categories]
custom_depth = "depth"
matte = "mask"
utility = "scalar"
[rules.nan_inf]
severity = "error"
[rules.technical_range]
severity = "error"
[rules.technical_range.parameters.ranges.custom_depth]
min = 0.0
[rules.technical_range.parameters.ranges.matte]
min = 0.0
max = 1.0
tolerance = 0.00001
[rules.technical_range.parameters.ranges.utility]
min = -2.0
max = 2.0
""",
        encoding="utf-8",
    )
    return path


def _write_exr(path):
    channels = {
        "custom_depth.R": np.array([[0, 10]], dtype=np.float32),
        "custom_depth.G": np.array([[2, -1]], dtype=np.float32),
        "custom_depth.B": np.array([[1, 20]], dtype=np.float32),
        "matte.R": np.array([[0, 1]], dtype=np.float32),
        "matte.G": np.array([[0.5, 1.5]], dtype=np.float32),
        "utility.X": np.array([[-1, 1]], dtype=np.float32),
        "utility.Y": np.array([[-3, 2]], dtype=np.float32),
        "crypto_object00.R": np.array([[-1e30, 1e30]], dtype=np.float32),
    }
    OpenEXR.File({"cryptomatte/1234567/name": "crypto_object"}, channels).write(str(path))


@pytest.mark.parametrize("isolated", [False, True])
def test_real_exr_preset_checks_every_component_and_exports_evidence(tmp_path, isolated):
    path = tmp_path / "shot.0001.exr"
    _write_exr(path)
    preset = load_rule_preset(_preset_file(tmp_path))
    options = AnalysisOptions(
        isolate_frames=isolated, aov_category_overrides=preset.aov_category_overrides
    )
    report = analyze(
        path, options, OpenEXRReader(preset.aov_category_overrides), rule_definitions=preset.rules
    )
    assert report.frame_count == 1 and report.failed_frame_count == 0
    assert report.metrics_by_aov == {}
    assert {finding.channel for finding in report.findings} == {
        "custom_depth.G",
        "matte.G",
        "utility.Y",
    }
    assert all(finding.affected_files == (path,) for finding in report.findings)
    assert "crypto_object00" in report.channel_metrics_by_aov
    payload = build_analysis_report_payload(report, options=options)
    assert json.loads(json.dumps(payload, allow_nan=False))["findings"][0]["metrics"]["per_frame"]
    html = build_analysis_html(report, options=options)
    assert "technical_range" in html and "custom_depth.G" in html and path.name in html
    changed = json.loads(json.dumps(payload))
    changed["metadata"]["effective_rules"][1]["parameters"]["ranges"]["custom_depth"]["min"] = 1
    with pytest.raises(ValueError, match="effective_rules"):
        compare_report_payloads(payload, changed)


def test_cli_and_gui_option_builder_share_preset_and_exit_status(tmp_path):
    from aovguard.gui.worker import build_analysis_options

    source = tmp_path / "shot.0001.exr"
    _write_exr(source)
    preset_path = _preset_file(tmp_path)
    output = tmp_path / "report.json"
    assert (
        cli.main(
            ["analyze", str(source), "--rules-config", str(preset_path), "--json", str(output)]
        )
        == 1
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    options, rules = build_analysis_options(
        luminance_model="Rec.709",
        rules_config=str(preset_path),
        selected_rule_ids={"technical_range", "nan_inf"},
    )
    report = analyze(
        source, options, OpenEXRReader(options.aov_category_overrides), rule_definitions=rules
    )
    assert payload["findings"] == build_analysis_report_payload(report, options=options)["findings"]


def test_json_and_toml_range_configs_are_equivalent(tmp_path):
    toml_preset = load_rule_preset(_preset_file(tmp_path))
    definition = toml_preset.rules[1]
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "rules": {
                    "technical_range": {
                        "severity": "error",
                        "parameters": dict(definition.parameters),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert load_rule_preset(path).rules[0] == definition


def test_real_multipart_ranges_preserve_part_identity_and_ignore_failed_frames(tmp_path):
    source = tmp_path / "shot.0001.exr"
    parts = [
        OpenEXR.Part({}, {"Z": np.array([[-1, 1]], dtype=np.float32)}, "left"),
        OpenEXR.Part({}, {"Z": np.array([[-1, 1]], dtype=np.float32)}, "right"),
    ]
    OpenEXR.File(parts).write(str(source))
    broken = tmp_path / "shot.0002.exr"
    broken.write_bytes(b"incomplete render")
    rule = _rule({"[part:left]::Z": {"min": 0}, "[part:right]::Z": {"min": -2}})
    report = analyze(
        tmp_path, AnalysisOptions(isolate_frames=True), OpenEXRReader(), rule_definitions=(rule,)
    )
    assert report.failed_frames == (broken,)
    (finding,) = (finding for finding in report.findings if finding.rule_id == "technical_range")
    assert finding.aov == "[part:left]::Z"
    assert finding.affected_files == (source,)
    assert set(finding.metrics["per_frame"]) == {str(source)}


def test_gui_loads_preset_and_exposes_exact_technical_finding(tmp_path, qt_application):
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtTest import QTest

    from aovguard.ui import MainWindow

    source = tmp_path / "shot.0001.exr"
    _write_exr(source)
    preset_path = _preset_file(tmp_path)
    preset = load_rule_preset(preset_path)
    options = AnalysisOptions(aov_category_overrides=preset.aov_category_overrides)
    report = analyze(
        source, options, OpenEXRReader(preset.aov_category_overrides), rule_definitions=preset.rules
    )
    window = MainWindow(settings=QSettings(str(tmp_path / "preferences.ini"), QSettings.IniFormat))
    try:
        checkbox = window.rule_checkboxes["technical_range"]
        assert not checkbox.isChecked()
        window.rules_edit.setText(str(preset_path))
        window.restore_rule_selection()
        assert checkbox.isChecked() and "preset" in checkbox.toolTip()
        QTest.keyClick(checkbox, Qt.Key_Space)
        assert not checkbox.isChecked()
        QTest.keyClick(checkbox, Qt.Key_Space)
        assert checkbox.isChecked()
        window.on_analysis_finished((report, options))
        assert window.findings_table.rowCount() == 3
        assert window.selected_finding.rule_id == "technical_range"
        assert window.selected_finding.file == source
    finally:
        window.close()
        qt_application.processEvents()
