from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import Imath
import numpy as np
import OpenEXR
import pytest

from aovguard.core.analysis import analyze
from aovguard.core.models import (
    AnalysisOptions,
    AOVCategory,
    AOVDescriptor,
    Severity,
)
from aovguard.io.reader import (
    OpenEXRReader,
    _inspection_from_file,
    _ordered_channels,
    _size_from_header,
)
from aovguard.rules.builtin import default_rule_definitions
from aovguard.rules.definitions import RuleDefinition


def _channel(value: float, width: int, height: int) -> bytes:
    return (np.ones((height, width), dtype=np.float32) * value).tobytes()


def _write_exr(
    path: Path,
    width: int,
    height: int,
    channels: dict[str, float],
    *,
    metadata: dict[str, str] | None = None,
) -> None:
    if metadata:
        pixels = {
            name: np.full((height, width), value, dtype=np.float32)
            for name, value in channels.items()
        }
        OpenEXR.File(metadata, pixels).write(str(path))
        return
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(width, height)
    header["channels"] = {name: Imath.Channel(pixel_type) for name in channels}
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {name: _channel(value, width, height) for name, value in channels.items()}
        )
    finally:
        output.close()


def _multichannel_exr(path: Path) -> Path:
    _write_exr(
        path,
        2,
        2,
        {
            "R": 1.0,
            "G": 2.0,
            "B": 3.0,
            "diffuse.R": 4.0,
            "diffuse.G": 5.0,
            "diffuse.B": 6.0,
            "Z": 10.0,
            "N.X": 0.0,
            "N.Y": 1.0,
            "N.Z": 0.0,
            "coverage": 1.0,
            "variance": 0.25,
        },
    )
    return path


def _arnold_technical_exr(path: Path) -> Path:
    _write_exr(
        path,
        2,
        2,
        {
            "R": 1.0,
            "G": 2.0,
            "B": 3.0,
            "N.R": 0.0,
            "N.G": 1.0,
            "N.B": 0.0,
            "P.R": 4.0,
            "P.G": 5.0,
            "P.B": 6.0,
            "Z.R": 10.0,
            "Z.G": 10.0,
            "Z.B": 10.0,
        },
    )
    return path


def _multipart_exr(path: Path) -> Path:
    pixels = np.ones((2, 2), dtype=np.float32)
    parts = [
        OpenEXR.Part(
            {},
            {"R": pixels, "G": pixels, "B": pixels},
            "beauty",
        ),
        OpenEXR.Part(
            {},
            {"R": pixels * 2, "G": pixels * 2, "B": pixels * 2},
            "secondary",
        ),
    ]
    OpenEXR.File(parts).write(str(path))
    return path


def test_openexr_reader_inspects_channels_and_aovs(tmp_path: Path) -> None:
    path = _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    inspection = reader.inspect(path)
    by_name = {aov.name: aov for aov in inspection.aovs}

    assert inspection.width == 2
    assert inspection.height == 2
    assert {"R", "G", "B", "diffuse.R", "diffuse.G", "diffuse.B", "Z"}.issubset(
        set(inspection.channels)
    )
    assert by_name["beauty"].category is AOVCategory.COLOR
    assert by_name["diffuse"].category is AOVCategory.COLOR
    assert by_name["Z"].category is AOVCategory.DEPTH
    assert by_name["N"].category is AOVCategory.VECTOR
    assert by_name["coverage"].category is AOVCategory.MASK
    assert by_name["variance"].category is AOVCategory.SCALAR


def test_openexr_reader_reads_supported_aovs_by_default(tmp_path: Path) -> None:
    path = _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    frame = reader.read_frame(path)

    assert set(frame.aovs) == {
        "beauty",
        "diffuse",
        "Z",
        "N",
        "coverage",
        "variance",
    }
    np.testing.assert_allclose(frame.aovs["beauty"][0, 0, :], [1.0, 2.0, 3.0])
    np.testing.assert_allclose(frame.aovs["diffuse"][0, 0, :], [4.0, 5.0, 6.0])


def test_openexr_reader_reads_scalar_and_vector_aovs_when_requested(tmp_path: Path) -> None:
    path = _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    frame = reader.read_frame(path, requested_aovs=["Z", "N"])

    assert set(frame.aovs) == {"Z", "N"}
    assert frame.aovs["Z"].shape == (2, 2)
    np.testing.assert_allclose(frame.aovs["Z"], np.ones((2, 2), dtype=np.float32) * 10)
    assert frame.aovs["N"].shape == (2, 2, 3)
    np.testing.assert_allclose(frame.aovs["N"][0, 0, :], [0.0, 1.0, 0.0])


def test_openexr_reader_reports_missing_requested_aov(tmp_path: Path) -> None:
    path = _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    with pytest.raises(RuntimeError, match="Requested AOV"):
        reader.read_frame(path, requested_aovs=["not_present"])


def test_openexr_reader_includes_arnold_technical_aovs_by_default(
    tmp_path: Path,
) -> None:
    path = _arnold_technical_exr(tmp_path / "arnold.1001.exr")
    reader = OpenEXRReader()

    inspection = reader.inspect(path)
    frame = reader.read_frame(path)
    by_name = {aov.name: aov for aov in inspection.aovs}

    assert by_name["N"].category is AOVCategory.VECTOR
    assert by_name["P"].category is AOVCategory.VECTOR
    assert by_name["Z"].category is AOVCategory.DEPTH
    assert set(frame.aovs) == {"beauty", "N", "P", "Z"}


def test_openexr_reader_reads_arnold_technical_aovs_when_requested(
    tmp_path: Path,
) -> None:
    path = _arnold_technical_exr(tmp_path / "arnold.1001.exr")
    reader = OpenEXRReader()

    frame = reader.read_frame(path, requested_aovs=["N", "P", "Z"])

    np.testing.assert_allclose(frame.aovs["N"][0, 0, :], [0.0, 1.0, 0.0])
    np.testing.assert_allclose(frame.aovs["P"][0, 0, :], [4.0, 5.0, 6.0])
    assert frame.aovs["Z"].shape == (2, 2, 3)
    np.testing.assert_allclose(frame.aovs["Z"], 10.0)


def test_multichannel_depth_checks_non_primary_components(tmp_path: Path) -> None:
    path = tmp_path / "depth.1001.exr"
    _write_exr(
        path,
        2,
        2,
        {
            "Z.R": 10.0,
            "Z.G": np.nan,
            "Z.B": np.inf,
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert set(report.channel_metrics_by_aov["Z"]) == {"Z.R", "Z.G", "Z.B"}
    assert report.channel_metrics_by_aov["Z"]["Z.G"].nan_count == 4
    assert report.channel_metrics_by_aov["Z"]["Z.B"].posinf_count == 4
    assert {finding.channel for finding in report.findings if finding.rule_id == "nan_inf"} == {
        "Z.G",
        "Z.B",
    }


def test_unknown_aov_is_retained_diagnosed_and_reported(tmp_path: Path) -> None:
    path = tmp_path / "custom.1001.exr"
    _write_exr(
        path,
        2,
        2,
        {
            "rendererData.foo": 1.0,
            "rendererData.bar": np.nan,
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert set(report.channel_metrics_by_aov["rendererData"]) == {
        "rendererData.foo",
        "rendererData.bar",
    }
    assert any(
        finding.rule_id == "unknown_aov" and finding.aov == "rendererData"
        for finding in report.findings
    )
    assert any(
        finding.rule_id == "nan_inf" and finding.channel == "rendererData.bar"
        for finding in report.findings
    )
    unknown = next(finding for finding in report.findings if finding.rule_id == "unknown_aov")
    assert unknown.metrics["provisional_category"] == "unknown"
    assert unknown.metrics["category_confidence"] == "insufficient_evidence"
    assert unknown.metrics["channels"] == [
        "rendererData.bar",
        "rendererData.foo",
    ]
    assert unknown.metrics["files"] == [str(path)]


def test_preset_override_classifies_unknown_aov(tmp_path: Path) -> None:
    path = tmp_path / "custom.1001.exr"
    _write_exr(
        path,
        1,
        1,
        {"rendererData.foo": 1.0, "rendererData.bar": 2.0},
    )
    reader = OpenEXRReader({"RENDERERDATA": AOVCategory.SCALAR})

    inspection = reader.inspect(path)
    report = analyze(tmp_path, AnalysisOptions(), reader)

    descriptor = next(aov for aov in inspection.aovs if aov.name == "rendererData")
    assert descriptor.category is AOVCategory.SCALAR
    assert descriptor.category_confidence == "preset_override"
    assert all(finding.rule_id != "unknown_aov" for finding in report.findings)


def test_ignored_override_retains_unusual_channels_without_unknown_finding(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unusual.1001.exr"
    _write_exr(
        path,
        1,
        1,
        {
            "VendorPayload.AUX0": 1.0,
            "VendorPayload.AUX1": np.nan,
            "VendorPayload.AUX2": 3.0,
            "VendorPayload.AUX3": 4.0,
        },
    )
    reader = OpenEXRReader({"vendorpayload": AOVCategory.IGNORED})

    report = analyze(tmp_path, AnalysisOptions(), reader)

    assert set(report.channel_metrics_by_aov["VendorPayload"]) == {
        "VendorPayload.AUX0",
        "VendorPayload.AUX1",
        "VendorPayload.AUX2",
        "VendorPayload.AUX3",
    }
    assert all(finding.rule_id != "unknown_aov" for finding in report.findings)
    assert any(
        finding.rule_id == "nan_inf" and finding.channel == "VendorPayload.AUX1"
        for finding in report.findings
    )


def test_multichannel_technical_anomalies_report_exact_non_primary_channels(
    tmp_path: Path,
) -> None:
    path = tmp_path / "technical.1001.exr"
    _write_exr(
        path,
        1,
        1,
        {
            "Z.R": 1.0,
            "Z.G": np.nan,
            "Z.B": np.inf,
            "mask.R": 0.0,
            "mask.G": -2.0,
            "mask.B": -np.inf,
            "customScalar.first": 1.0,
            "customScalar.second": 2.0,
            "customScalar.third": 2_000_000.0,
        },
    )
    definitions = (
        RuleDefinition(id="nan_inf", severity=Severity.ERROR),
        RuleDefinition(id="negative_values", severity=Severity.WARNING),
        RuleDefinition(
            id="extreme_values",
            severity=Severity.WARNING,
            parameters={"max_absolute": 1_000_000.0},
        ),
    )
    reader = OpenEXRReader({"CUSTOMSCALAR": AOVCategory.SCALAR})

    report = analyze(
        tmp_path,
        AnalysisOptions(),
        reader,
        rule_definitions=definitions,
    )

    assert set(report.channel_metrics_by_aov["Z"]) == {"Z.R", "Z.G", "Z.B"}
    assert set(report.channel_metrics_by_aov["mask"]) == {
        "mask.R",
        "mask.G",
        "mask.B",
    }
    assert set(report.channel_metrics_by_aov["customScalar"]) == {
        "customScalar.first",
        "customScalar.second",
        "customScalar.third",
    }
    finding_channels = {(finding.rule_id, finding.channel) for finding in report.findings}
    assert ("nan_inf", "Z.G") in finding_channels
    assert ("nan_inf", "Z.B") in finding_channels
    assert ("nan_inf", "mask.B") in finding_channels
    assert ("negative_values", "mask.G") in finding_channels
    assert ("extreme_values", "customScalar.third") in finding_channels


def test_core_analyze_can_use_openexr_reader(tmp_path: Path) -> None:
    _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    report = analyze(tmp_path, AnalysisOptions(), reader)

    assert report.frame_count == 1
    assert set(report.metrics_by_aov) == {"beauty", "diffuse"}
    assert report.metrics_by_aov["beauty"].pixel_count == 4
    assert report.metrics_by_aov["beauty"].avg_luminance == pytest.approx(1.8596)
    assert report.metrics_by_aov["diffuse"].avg_luminance == pytest.approx(4.8596)
    assert report.technical_aov_count == 4
    assert set(report.channel_metrics_by_aov["N"]) == {"N.X", "N.Y", "N.Z"}
    assert set(report.channel_metrics_by_aov["Z"]) == {"Z"}
    assert report.channel_metrics_by_aov["coverage"]["coverage"].avg_value == 1.0
    assert report.channel_metrics_by_aov["variance"]["variance"].avg_value == 0.25
    assert report.findings == ()


def test_core_analyze_keeps_arnold_rgb_technical_channels_out_of_luminance(
    tmp_path: Path,
) -> None:
    _arnold_technical_exr(tmp_path / "arnold.1001.exr")

    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert set(report.metrics_by_aov) == {"beauty"}
    assert report.technical_aov_count == 3
    assert set(report.channel_metrics_by_aov["N"]) == {"N.R", "N.G", "N.B"}
    assert set(report.channel_metrics_by_aov["P"]) == {"P.R", "P.G", "P.B"}
    assert set(report.channel_metrics_by_aov["Z"]) == {"Z.R", "Z.G", "Z.B"}
    assert report.channel_metrics_by_aov["Z"]["Z.R"].avg_value == 10.0


def test_cryptomatte_metadata_excludes_id_channels_from_luminance(tmp_path: Path) -> None:
    path = tmp_path / "shot.0001.exr"
    _write_exr(
        path,
        2,
        2,
        {
            "R": 0.5, "G": 0.5, "B": 0.5,
            "crypto_material.R": -2.8e20,
            "crypto_material.G": 0.75,
            "crypto_material.B": 2.1e20,
            "crypto_material00.R": 1.2e20,
            "crypto_material00.G": 0.25,
            "crypto_material00.B": float("nan"),
            "crypto_material00.A": 0.0,
            "crypto_materiality.R": 0.1,
            "crypto_materiality.G": 0.2,
            "crypto_materiality.B": 0.3,
        },
        metadata={"cryptomatte/1234567/name": "crypto_material"},
    )

    inspection = OpenEXRReader().inspect(path)
    categories = {aov.name: aov.category for aov in inspection.aovs}
    assert categories["crypto_material"] is AOVCategory.CRYPTOMATTE
    assert categories["crypto_material00"] is AOVCategory.CRYPTOMATTE
    assert categories["crypto_materiality"] is AOVCategory.COLOR

    report = analyze(path, AnalysisOptions(), OpenEXRReader())
    assert set(report.metrics_by_aov) == {"beauty", "crypto_materiality"}
    assert "crypto_material" not in report.series_metrics_by_aov
    assert set(report.channel_metrics_by_aov["crypto_material00"]) == {
        "crypto_material00.R", "crypto_material00.G", "crypto_material00.B",
        "crypto_material00.A",
    }
    assert any(
        finding.rule_id == "nan_inf"
        and finding.channel == "crypto_material00.B"
        for finding in report.findings
    )
    definitions = tuple(
        replace(definition, enabled=True)
        if definition.id == "extreme_values" else definition
        for definition in default_rule_definitions()
    )
    with_extreme = analyze(path, AnalysisOptions(), OpenEXRReader(), rule_definitions=definitions)
    assert not any(finding.rule_id == "extreme_values" for finding in with_extreme.findings)


def test_core_analysis_opens_each_frame_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _multichannel_exr(tmp_path / "shot.1001.exr")
    original_file = OpenEXR.File
    opened: list[str] = []

    def counting_file(*args, **kwargs):
        opened.append(str(args[0]))
        return original_file(*args, **kwargs)

    monkeypatch.setattr(OpenEXR, "File", counting_file)

    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert report.frame_count == 1
    assert len(opened) == 1


def test_analysis_reports_real_mixed_resolutions_and_aov_structures(tmp_path: Path) -> None:
    first = tmp_path / "shot.1001.exr"
    second = tmp_path / "shot.1002.exr"
    _write_exr(
        first,
        2,
        2,
        {
            "R": 1.0,
            "G": 1.0,
            "B": 1.0,
            "diffuse.R": 0.5,
            "diffuse.G": 0.5,
            "diffuse.B": 0.5,
        },
    )
    _write_exr(second, 4, 3, {"R": 2.0, "G": 2.0, "B": 2.0})

    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert report.frame_count == 2
    assert {(item.width, item.height) for item in report.inspections} == {(2, 2), (4, 3)}
    assert {finding.rule_id for finding in report.findings}.issuperset(
        {"resolution_mismatch", "aov_structure_mismatch"}
    )


def test_analysis_continues_after_corrupt_frame_between_valid_exrs(tmp_path: Path) -> None:
    first = tmp_path / "shot.1001.exr"
    broken = tmp_path / "shot.1002.exr"
    third = tmp_path / "shot.1003.exr"
    channels = {"R": 1.0, "G": 1.0, "B": 1.0}
    _write_exr(first, 3, 2, channels)
    broken.write_bytes(b"not an OpenEXR file")
    _write_exr(third, 3, 2, channels)

    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert report.discovered_frame_count == 3
    assert report.successful_frames == (first, third)
    assert report.failed_frames == (broken,)
    read_error = next(finding for finding in report.findings if finding.rule_id == "read_frame")
    assert read_error.file == broken


def test_openexr_reader_detects_multipart_structure(tmp_path: Path) -> None:
    path = _multipart_exr(tmp_path / "multipart.exr")
    reader = OpenEXRReader()

    inspection = reader.inspect(path)
    frame = reader.read_frame(path)

    assert inspection.part_count == 2
    assert not inspection.is_deep
    assert inspection.unsupported_reason is not None
    assert frame.inspection.part_count == 2
    assert frame.aovs == {}


def test_reader_validates_backend_metadata_and_channel_layout() -> None:
    data_window = SimpleNamespace(
        min=SimpleNamespace(x=2, y=3),
        max=SimpleNamespace(x=5, y=7),
    )
    assert _size_from_header({"dataWindow": data_window}) == (4, 5)

    incomplete = AOVDescriptor(
        "diffuse",
        ("diffuse.R", "diffuse.G"),
        AOVCategory.COLOR,
    )
    with pytest.raises(RuntimeError, match="missing channel suffix"):
        _ordered_channels(incomplete, ("R", "G", "B"))

    with pytest.raises(RuntimeError, match="no image parts"):
        _inspection_from_file(SimpleNamespace(parts=[]), Path("empty.exr"))


def test_reader_reports_missing_and_malformed_channel_data() -> None:
    reader = OpenEXRReader()
    missing_part = SimpleNamespace(channels={})
    with pytest.raises(RuntimeError, match="channel not found"):
        reader._read_channel(missing_part, "R", 2, 2)

    malformed_part = SimpleNamespace(
        channels={"R": SimpleNamespace(pixels=np.ones((1, 4), dtype=np.float32))}
    )
    with pytest.raises(RuntimeError, match="unsupported sampled shape"):
        reader._read_channel(malformed_part, "R", 2, 2)

    unknown = AOVDescriptor(
        "custom",
        ("custom.foo", "custom.bar"),
        AOVCategory.UNKNOWN,
    )
    unknown_part = SimpleNamespace(
        channels={
            "custom.foo": SimpleNamespace(pixels=np.ones((2, 2), dtype=np.float32)),
            "custom.bar": SimpleNamespace(pixels=np.full((2, 2), 2.0, dtype=np.float32)),
        }
    )
    values = reader._read_descriptor(unknown_part, unknown, 2, 2)
    assert values.shape == (2, 2, 2)
    np.testing.assert_allclose(values[0, 0, :], [1.0, 2.0])
