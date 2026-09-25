from pathlib import Path

import pytest

from aovguard.discovery.frame_discovery import discover_frames


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_discover_frames_accepts_single_exr_file(tmp_path: Path) -> None:
    frame = tmp_path / "shot.1001.exr"
    _touch(frame)

    result = discover_frames(frame)

    assert result.frames == (frame,)
    assert result.frame_count == 1
    assert result.warnings == ()


def test_discover_frames_uses_direct_exrs(tmp_path: Path) -> None:
    frame_a = tmp_path / "shot.1002.exr"
    frame_b = tmp_path / "shot.1001.exr"
    _touch(frame_a)
    _touch(frame_b)

    result = discover_frames(tmp_path)

    assert result.frames == (frame_b, frame_a)
    assert result.direct_frames == (frame_b, frame_a)
    assert result.nested_frames == ()


def test_discover_frames_uses_natural_numeric_order(tmp_path: Path) -> None:
    frame_999 = tmp_path / "shot.999.exr"
    frame_1000 = tmp_path / "shot.1000.exr"
    frame_1001 = tmp_path / "shot.1001.exr"
    _touch(frame_1001)
    _touch(frame_999)
    _touch(frame_1000)

    result = discover_frames(tmp_path)

    assert result.frames == (frame_999, frame_1000, frame_1001)


def test_discover_frames_uses_nested_exrs_when_no_direct_exrs(tmp_path: Path) -> None:
    nested = tmp_path / "beauty" / "shot.1001.exr"
    _touch(nested)

    result = discover_frames(tmp_path)

    assert result.frames == (nested,)
    assert result.direct_frames == ()
    assert result.nested_frames == (nested,)


def test_discover_frames_warns_when_direct_and_nested_exrs_are_mixed(tmp_path: Path) -> None:
    direct = tmp_path / "shot.1001.exr"
    nested = tmp_path / "beauty" / "shot.1002.exr"
    _touch(direct)
    _touch(nested)

    result = discover_frames(tmp_path)

    assert result.frames == (direct,)
    assert result.nested_frames == (nested,)
    assert result.warnings == (
        "Direct EXR files were found, so one-level nested EXR files were ignored.",
    )


def test_discover_frames_returns_empty_result_for_empty_folder(tmp_path: Path) -> None:
    result = discover_frames(tmp_path)

    assert result.frames == ()
    assert result.frame_count == 0
    assert result.warnings == ()


def test_discover_frames_rejects_non_exr_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("not an exr")

    with pytest.raises(ValueError, match="not an EXR"):
        discover_frames(path)


def test_discover_frames_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_frames(tmp_path / "missing")


def test_discover_frames_filters_by_pattern(tmp_path: Path) -> None:
    beauty = tmp_path / "beauty.1001.exr"
    diffuse = tmp_path / "diffuse.1001.exr"
    _touch(beauty)
    _touch(diffuse)

    result = discover_frames(tmp_path, pattern="beauty.*.exr")

    assert result.frames == (beauty,)


def test_discover_frames_recursive_includes_direct_and_bounded_nested_frames(
    tmp_path: Path,
) -> None:
    direct = tmp_path / "shot.1001.exr"
    level_one = tmp_path / "renders" / "shot.1002.exr"
    level_two = tmp_path / "renders" / "deep" / "shot.1003.exr"
    _touch(direct)
    _touch(level_one)
    _touch(level_two)

    bounded = discover_frames(tmp_path, recursive=True, max_depth=1)
    unbounded = discover_frames(tmp_path, recursive=True, max_depth=None)

    assert bounded.frames == (direct, level_one)
    assert unbounded.frames == (direct, level_one, level_two)
    assert bounded.warnings == ()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pattern": ""}, "must not be empty"),
        ({"pattern": "renders/*.exr"}, "filename pattern"),
        ({"recursive": True, "max_depth": -1}, "non-negative"),
    ],
)
def test_discover_frames_validates_options(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        discover_frames(tmp_path, **kwargs)
