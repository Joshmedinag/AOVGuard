"""Native flat-multipart regressions for channel and part identity."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import OpenEXR
import pytest

from aovguard.core.analysis import analyze
from aovguard.core.models import AnalysisOptions, AOVCategory
from aovguard.io.reader import OpenEXRReader


def _pixels(value: float = 1.0, shape: tuple[int, int] = (2, 2)) -> dict[str, np.ndarray]:
    return {name: np.full(shape, value, dtype=np.float32) for name in ("R", "G", "B")}


def _write_parts(path: Path, parts: list) -> Path:
    OpenEXR.File(parts).write(str(path))
    return path


def test_multipart_parts_have_exact_qualified_channels_and_independent_aovs(tmp_path: Path) -> None:
    left = {**_pixels(1.0), "A": np.full((2, 2), np.nan, dtype=np.float32)}
    right = {**_pixels(2.0), "A": np.full((2, 2), np.inf, dtype=np.float32)}
    path = _write_parts(tmp_path / "stereo.exr", [
        OpenEXR.Part({"view": "left"}, left, "left"),
        OpenEXR.Part({"view": "right"}, right, "right"),
    ])

    frame = OpenEXRReader().read_frame(path)

    assert frame.inspection.unsupported_reason is None
    assert set(frame.aovs) == {"[part:left]::beauty", "[part:right]::beauty"}
    assert set(frame.channel_data) == {
        f"[part:{name}]::{channel}" for name in ("left", "right") for channel in ("R", "G", "B", "A")
    }
    assert frame.inspection.parts[0].view == "left"
    assert frame.inspection.parts[1].view == "right"
    assert frame.inspection.parts[0].channels == ("A", "B", "G", "R")
    descriptor = frame.inspection.parts[1].aovs[0]
    assert descriptor.original_name == "beauty"
    assert descriptor.original_channels == ("R", "G", "B", "A")
    assert descriptor.part_index == 1
    assert np.isnan(frame.channel_data["[part:left]::A"]).all()
    assert np.isposinf(frame.channel_data["[part:right]::A"]).all()
    np.testing.assert_array_equal(frame.aovs["[part:left]::beauty"], 1.0)
    np.testing.assert_array_equal(frame.aovs["[part:right]::beauty"], 2.0)

    report = analyze(path, AnalysisOptions(), OpenEXRReader())
    assert report.frame_count == 1
    assert set(report.metrics_by_aov) == set(frame.aovs)
    assert report.channel_metrics_by_aov["[part:left]::beauty"]["[part:left]::A"].nan_count == 4
    assert any(finding.channel == "[part:right]::A" for finding in report.findings)


def test_parts_decode_against_their_own_stored_windows(tmp_path: Path) -> None:
    display = (np.array([0, 0], dtype=np.int32), np.array([9, 9], dtype=np.int32))
    left_window = (np.array([1, 2], dtype=np.int32), np.array([3, 3], dtype=np.int32))
    right_window = (np.array([4, 5], dtype=np.int32), np.array([5, 7], dtype=np.int32))
    path = _write_parts(tmp_path / "cropped.exr", [
        OpenEXR.Part({"displayWindow": display, "dataWindow": left_window}, _pixels(1.0, (2, 3)), "left"),
        OpenEXR.Part({"displayWindow": display, "dataWindow": right_window}, _pixels(2.0, (3, 2)), "right"),
    ])

    frame = OpenEXRReader().read_frame(path)

    assert (frame.width, frame.height) == (3, 2)
    assert frame.aovs["[part:left]::beauty"].shape == (2, 3, 3)
    assert frame.aovs["[part:right]::beauty"].shape == (3, 2, 3)
    assert frame.inspection.parts[0].data_window == ((1, 2), (3, 3))
    assert frame.inspection.parts[1].data_window == ((4, 5), (5, 7))
    assert frame.inspection.parts[1].display_window == ((0, 0), (9, 9))


def test_named_part_keys_survive_reordering_and_an_absent_part(tmp_path: Path) -> None:
    first = _write_parts(tmp_path / "first.exr", [
        OpenEXR.Part({}, _pixels(1.0), "left"),
        OpenEXR.Part({}, _pixels(2.0), "right"),
        OpenEXR.Part({}, _pixels(3.0), "auxiliary"),
    ])
    second = _write_parts(tmp_path / "second.exr", [
        OpenEXR.Part({}, _pixels(2.0), "right"),
        OpenEXR.Part({}, _pixels(1.0), "left"),
    ])
    reader = OpenEXRReader()

    first_frame, second_frame = reader.read_frame(first), reader.read_frame(second)

    for name in ("[part:left]::beauty", "[part:right]::beauty"):
        np.testing.assert_array_equal(first_frame.aovs[name], second_frame.aovs[name])
    assert first_frame.inspection.parts[1].aovs[0].part_index == 1
    assert second_frame.inspection.parts[0].aovs[0].part_index == 0


def test_cryptomatte_metadata_is_interpreted_per_part(tmp_path: Path) -> None:
    crypto = {
        f"crypto00.{channel}": np.ones((2, 2), dtype=np.float32) for channel in ("R", "G", "B", "A")
    }
    path = _write_parts(tmp_path / "crypto.exr", [
        OpenEXR.Part({"cryptomatte/1234567/name": "crypto"}, crypto, "ids"),
        OpenEXR.Part({}, crypto, "color"),
    ])

    inspection = OpenEXRReader().inspect(path)

    assert inspection.parts[0].aovs[0].category is AOVCategory.CRYPTOMATTE
    assert inspection.parts[1].aovs[0].category is AOVCategory.COLOR
    assert inspection.aovs == inspection.parts[0].aovs + inspection.parts[1].aovs


def test_uint_channel_precision_survives_multipart_decoding(tmp_path: Path) -> None:
    ids = np.array([[16_777_216, 16_777_217, 4_294_967_295]], dtype=np.uint32)
    path = _write_parts(tmp_path / "ids.exr", [
        OpenEXR.Part({}, {"object_id": ids}, "ids"),
        OpenEXR.Part({}, _pixels(1.0, (1, 3)), "color"),
    ])

    frame = OpenEXRReader().read_frame(path)

    assert frame.channel_data["[part:ids]::object_id"].dtype == np.uint32
    np.testing.assert_array_equal(frame.channel_data["[part:ids]::object_id"], ids)


def test_original_category_override_applies_to_all_parts_and_exact_override_wins(tmp_path: Path) -> None:
    channels = {
        "custom.foo": np.ones((2, 2), dtype=np.float32),
        "custom.bar": np.ones((2, 2), dtype=np.float32),
    }
    path = _write_parts(tmp_path / "overrides.exr", [
        OpenEXR.Part({}, channels, "left"), OpenEXR.Part({}, channels, "right"),
    ])
    reader = OpenEXRReader({"CUSTOM": "scalar", "[PART:LEFT]::CUSTOM": "ignored"})

    frame = reader.read_frame(path)

    assert frame.inspection.parts[0].aovs[0].category is AOVCategory.IGNORED
    assert frame.inspection.parts[1].aovs[0].category is AOVCategory.SCALAR
    assert all(descriptor.category_confidence == "preset_override" for descriptor in frame.inspection.aovs)


def test_qualified_requested_aov_does_not_drop_other_part_integrity(tmp_path: Path) -> None:
    path = _write_parts(tmp_path / "selection.exr", [
        OpenEXR.Part({}, _pixels(1.0), "left"), OpenEXR.Part({}, _pixels(2.0), "right"),
    ])

    frame = OpenEXRReader().read_frame(path, requested_aovs=["[part:right]::beauty"])

    assert set(frame.aovs) == {"[part:right]::beauty"}
    assert len(frame.channel_data) == 6
    with pytest.raises(RuntimeError, match="Requested AOV"):
        OpenEXRReader().read_frame(path, requested_aovs=["beauty"])


def test_part_and_aov_delimiters_are_escaped_without_collisions(tmp_path: Path) -> None:
    unusual = {f"beauty]::custom.{channel}": value for channel, value in _pixels(2.0).items()}
    path = _write_parts(tmp_path / "escaped.exr", [
        OpenEXR.Part({}, _pixels(1.0), "right]::foo%"),
        OpenEXR.Part({}, unusual, "right%5D%3A%3Afoo%25"),
    ])

    frame = OpenEXRReader().read_frame(path)

    assert set(frame.aovs) == {
        "[part:right%5D%3A%3Afoo%25]::beauty",
        "[part:right%255D%253A%253Afoo%2525]::beauty%5D%3A%3Acustom",
    }
    assert len(set(frame.inspection.channels)) == 6


@pytest.mark.parametrize("names", [(None, None), ("same", "same")])
def test_missing_or_duplicate_part_names_use_indexed_identities(
    monkeypatch: pytest.MonkeyPatch, names: tuple[str | None, str | None],
) -> None:
    parts = [
        SimpleNamespace(
            header={
                "name": name,
                "dataWindow": (np.array([0, 0]), np.array([1, 1])),
                "channels": [SimpleNamespace(name=channel) for channel in ("R", "G", "B")],
            },
            type=lambda: OpenEXR.scanlineimage,
        )
        for name in names
    ]
    monkeypatch.setattr(OpenEXR, "File", lambda *_args, **_kwargs: SimpleNamespace(parts=parts))

    inspection = OpenEXRReader().inspect(Path("unnamed.exr"))

    expected = (
        {"[part-index:0]::beauty", "[part-index:1]::beauty"}
        if names[0] is None else {"[part-index:0:same]::beauty", "[part-index:1:same]::beauty"}
    )
    assert {descriptor.name for descriptor in inspection.aovs} == expected
    assert len(set(inspection.channels)) == 6


def test_any_deep_part_rejects_the_whole_file_before_pixel_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = [
        SimpleNamespace(
            header={
                "name": name,
                "dataWindow": (np.array([0, 0]), np.array([1, 1])),
                "channels": [SimpleNamespace(name="Z")],
            },
            type=lambda index=index: OpenEXR.deepscanline if index else OpenEXR.scanlineimage,
        )
        for index, name in enumerate(("flat", "deep"))
    ]
    calls: list[bool] = []

    def header_only_file(_path: str, *, separate_channels: bool, header_only: bool = False):
        calls.append(header_only)
        assert separate_channels and header_only
        return SimpleNamespace(parts=parts)

    monkeypatch.setattr(OpenEXR, "File", header_only_file)

    frame = OpenEXRReader().read_frame(Path("mixed.exr"))

    assert calls == [True]
    assert frame.inspection.is_deep
    assert not frame.aovs and not frame.channel_data


def test_partial_part_decode_is_detected_against_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    complete = _write_parts(tmp_path / "complete.exr", [
        OpenEXR.Part({}, _pixels(1.0), "left"), OpenEXR.Part({}, _pixels(2.0), "right"),
    ])
    partial = tmp_path / "partial.exr"
    OpenEXR.File({}, _pixels(1.0)).write(str(partial))
    original_file = OpenEXR.File

    def inconsistent_file(path: str, **kwargs):
        return original_file(path if kwargs.get("header_only") else str(partial), **kwargs)

    monkeypatch.setattr(OpenEXR, "File", inconsistent_file)

    with pytest.raises(RuntimeError, match="partially decoded"):
        OpenEXRReader().read_frame(complete)


def test_single_part_keys_remain_unqualified(tmp_path: Path) -> None:
    path = tmp_path / "single.exr"
    OpenEXR.File({}, _pixels()).write(str(path))

    frame = OpenEXRReader().read_frame(path)

    assert set(frame.aovs) == {"beauty"}
    assert set(frame.channel_data) == {"R", "G", "B"}
    assert frame.inspection.parts[0].aovs == frame.inspection.aovs
    assert frame.inspection.parts[0].index == 0
