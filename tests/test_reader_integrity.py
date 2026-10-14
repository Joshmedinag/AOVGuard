"""Regression coverage for channel preservation and metadata boundaries."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import OpenEXR
import pytest

from aovguard.core.models import AOVCategory
from aovguard.io.reader import OpenEXRReader


def _write_pixels(path: Path, pixels: dict[str, np.ndarray], header: dict | None = None) -> None:
    OpenEXR.File(header or {}, pixels).write(str(path))


def test_alpha_and_auxiliary_channels_remain_available_for_integrity(tmp_path: Path) -> None:
    path = tmp_path / "rgba.exr"
    pixels = {
        "beauty.R": np.ones((2, 2), dtype=np.float32),
        "beauty.G": np.ones((2, 2), dtype=np.float32),
        "beauty.B": np.ones((2, 2), dtype=np.float32),
        "beauty.A": np.full((2, 2), np.nan, dtype=np.float32),
        "beauty.AUX": np.full((2, 2), np.inf, dtype=np.float32),
        "N.X": np.ones((2, 2), dtype=np.float32),
        "N.Y": np.ones((2, 2), dtype=np.float32),
        "N.Z": np.ones((2, 2), dtype=np.float32),
        "N.extra": np.full((2, 2), -np.inf, dtype=np.float32),
    }
    _write_pixels(path, pixels)

    frame = OpenEXRReader().read_frame(path)

    assert set(frame.channel_data) == set(pixels)
    assert frame.aovs["beauty"].shape == (2, 2, 3)
    assert np.isfinite(frame.aovs["beauty"]).all()
    assert np.isnan(frame.channel_data["beauty.A"]).all()
    assert np.isposinf(frame.channel_data["beauty.AUX"]).all()
    assert np.isneginf(frame.channel_data["N.extra"]).all()
    with pytest.raises(TypeError):
        frame.channel_data["unexpected"] = pixels["beauty.R"]  # type: ignore[index]


def test_reader_uses_the_same_rgb_aliases_as_inspection(tmp_path: Path) -> None:
    path = tmp_path / "aliases.exr"
    _write_pixels(path, {
        "specular.red": np.full((1, 2), 1.0, dtype=np.float32),
        "specular.Green": np.full((1, 2), 2.0, dtype=np.float32),
        "specular.BLUE": np.full((1, 2), 3.0, dtype=np.float32),
    })

    frame = OpenEXRReader().read_frame(path)

    assert frame.inspection.aovs[0].category is AOVCategory.COLOR
    np.testing.assert_array_equal(frame.aovs["specular"][0, 0], [1.0, 2.0, 3.0])


def test_root_and_named_beauty_do_not_overwrite_pixels(tmp_path: Path) -> None:
    path = tmp_path / "beauties.exr"
    _write_pixels(path, {
        name: np.full((1, 1), value, dtype=np.float32)
        for name, value in {
            "R": 1.0, "G": 2.0, "B": 3.0,
            "beauty.R": 4.0, "beauty.G": 5.0, "beauty.B": 6.0,
        }.items()
    })

    frame = OpenEXRReader().read_frame(path)

    assert set(frame.aovs) == {"beauty [root]", "beauty"}
    np.testing.assert_array_equal(frame.aovs["beauty [root]"][0, 0], [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(frame.aovs["beauty"][0, 0], [4.0, 5.0, 6.0])


def test_uint_ids_preserve_values_above_float32_integer_precision(tmp_path: Path) -> None:
    path = tmp_path / "ids.exr"
    ids = np.array([[16_777_216, 16_777_217, 4_294_967_295]], dtype=np.uint32)
    _write_pixels(path, {"object_id": ids})

    frame = OpenEXRReader().read_frame(path)

    assert frame.channel_data["object_id"].dtype == np.uint32
    np.testing.assert_array_equal(frame.channel_data["object_id"], ids)
    assert frame.aovs["object_id"] is frame.channel_data["object_id"]


@pytest.mark.parametrize("suffixes", [("X", "Y"), ("U", "V")])
def test_preset_vector_override_supports_two_components(
    tmp_path: Path, suffixes: tuple[str, str],
) -> None:
    path = tmp_path / "motion.exr"
    _write_pixels(path, {
        f"motion.{suffix}": np.full((1, 1), index + 1, dtype=np.float32)
        for index, suffix in enumerate(suffixes)
    })

    frame = OpenEXRReader({"motion": "vector"}).read_frame(path)

    assert frame.inspection.aovs[0].category is AOVCategory.VECTOR
    assert frame.aovs["motion"].shape == (1, 1, 2)
    np.testing.assert_array_equal(frame.aovs["motion"][0, 0], [1.0, 2.0])


def test_requested_aov_views_do_not_drop_exact_source_channels(tmp_path: Path) -> None:
    path = tmp_path / "selected.exr"
    _write_pixels(path, {
        "R": np.ones((1, 1), dtype=np.float32),
        "G": np.ones((1, 1), dtype=np.float32),
        "B": np.ones((1, 1), dtype=np.float32),
        "Z": np.ones((1, 1), dtype=np.float32),
    })

    frame = OpenEXRReader().read_frame(path, requested_aovs=["Z"])

    assert set(frame.aovs) == {"Z"}
    assert set(frame.channel_data) == {"R", "G", "B", "Z"}


def test_data_and_display_windows_keep_origins_and_distinct_sizes(tmp_path: Path) -> None:
    path = tmp_path / "cropped.exr"
    _write_pixels(path, {"Z": np.ones((2, 3), dtype=np.float32)}, {
        "dataWindow": (np.array([10, 20], dtype=np.int32), np.array([12, 21], dtype=np.int32)),
        "displayWindow": (np.array([0, 0], dtype=np.int32), np.array([1919, 1079], dtype=np.int32)),
    })

    frame = OpenEXRReader().read_frame(path)

    assert (frame.width, frame.height) == (3, 2)
    assert frame.inspection.data_window == ((10, 20), (12, 21))
    assert frame.inspection.display_window == ((0, 0), (1919, 1079))
    assert (frame.inspection.display_width, frame.inspection.display_height) == (1920, 1080)
    assert frame.channel_data["Z"].shape == (2, 3)


@pytest.mark.parametrize("deep,part_count", [(True, 1), (True, 2)])
def test_unsupported_structures_are_rejected_before_decoding(
    monkeypatch: pytest.MonkeyPatch, deep: bool, part_count: int,
) -> None:
    part = SimpleNamespace(
        header={
            "dataWindow": (np.array([0, 0]), np.array([1, 1])),
            "channels": [SimpleNamespace(name="R")],
        },
        type=lambda: OpenEXR.deepscanline if deep else OpenEXR.scanlineimage,
    )
    calls: list[bool] = []

    def header_only_file(path: str, *, separate_channels: bool, header_only: bool = False):
        calls.append(header_only)
        assert separate_channels
        assert header_only, "Unsupported structures must never decode pixels"
        return SimpleNamespace(parts=[part] * part_count)

    monkeypatch.setattr(OpenEXR, "File", header_only_file)

    frame = OpenEXRReader().read_frame(Path("unsupported.exr"))

    assert calls == [True]
    assert frame.inspection.unsupported_reason is not None
    assert not frame.aovs
    assert not frame.channel_data


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64, np.uint32])
def test_channel_decoding_reuses_sufficient_precision_buffers(dtype) -> None:
    pixels = np.ones((2, 2), dtype=dtype)
    part = SimpleNamespace(channels={"custom": SimpleNamespace(pixels=pixels)})

    array = OpenEXRReader()._read_channel(part, "custom", 2, 2)

    if dtype is np.float16:
        assert array.dtype == np.float32
    else:
        assert array is pixels
        assert array.dtype == pixels.dtype
