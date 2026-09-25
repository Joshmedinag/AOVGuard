"""Bounded EXR file discovery for files, folders and nested sequences."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FrameDiscoveryResult:
    """The exact EXR frames selected for processing."""

    source: Path
    frames: tuple[Path, ...]
    direct_frames: tuple[Path, ...]
    nested_frames: tuple[Path, ...]
    warnings: tuple[str, ...] = ()

    @property
    def frame_count(self) -> int:
        """Return the number of discovered EXR candidates."""

        return len(self.frames)


def _natural_name_key(path: Path) -> tuple[tuple[int, object], ...]:
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.lower())
        for part in re.split(r"(\d+)", path.name)
    )


def _path_sort_key(path: Path) -> tuple[str, tuple[tuple[int, object], ...]]:
    return str(path.parent).lower(), _natural_name_key(path)


def _matches_frame_pattern(path: Path, pattern: str) -> bool:
    return path.suffix.lower() == ".exr" and fnmatch(
        path.name.casefold(),
        pattern.casefold(),
    )


def _sorted_exr_files(folder: Path, pattern: str) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (
                path
                for path in folder.iterdir()
                if path.is_file() and _matches_frame_pattern(path, pattern)
            ),
            key=_path_sort_key,
        )
    )


def discover_frames(
    source: str | Path,
    *,
    pattern: str = "*.exr",
    recursive: bool = False,
    max_depth: int | None = 1,
) -> FrameDiscoveryResult:
    """Discover the exact EXR files that should be processed.

    Default policy:
    - a single EXR file is accepted directly;
    - direct EXRs in a folder take priority;
    - one-level nested EXRs are used only when no direct EXRs exist;
    - mixed direct and nested inputs produce a warning.

    Recursive mode includes matching direct and nested EXRs up to ``max_depth``.
    """

    if not pattern.strip():
        raise ValueError("Frame pattern must not be empty.")
    if "/" in pattern or "\\" in pattern:
        raise ValueError("Frame pattern must be a filename pattern, not a path.")
    if max_depth is not None and max_depth < 0:
        raise ValueError("Discovery max_depth must be non-negative or None.")

    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    if source_path.is_file():
        if source_path.suffix.lower() != ".exr":
            raise ValueError(f"Input file is not an EXR: {source_path}")
        resolved = (source_path,)
        return FrameDiscoveryResult(
            source=source_path,
            frames=resolved,
            direct_frames=resolved,
            nested_frames=(),
        )

    if not source_path.is_dir():
        raise NotADirectoryError(source_path)

    direct_frames = _sorted_exr_files(source_path, pattern)
    if recursive:
        nested_frames = tuple(
            sorted(
                (
                    frame
                    for frame in source_path.rglob("*")
                    if frame.is_file()
                    and _matches_frame_pattern(frame, pattern)
                    and frame.parent != source_path
                    and (
                        max_depth is None
                        or len(frame.relative_to(source_path).parts) - 1 <= max_depth
                    )
                ),
                key=_path_sort_key,
            )
        )
        return FrameDiscoveryResult(
            source=source_path,
            frames=tuple(sorted(direct_frames + nested_frames, key=_path_sort_key)),
            direct_frames=direct_frames,
            nested_frames=nested_frames,
        )

    nested_frames = tuple(
        sorted(
            (
                frame
                for subfolder in source_path.iterdir()
                if subfolder.is_dir()
                for frame in _sorted_exr_files(subfolder, pattern)
            ),
            key=_path_sort_key,
        )
    )

    warnings: tuple[str, ...] = ()
    frames = direct_frames
    if direct_frames and nested_frames:
        warnings = ("Direct EXR files were found, so one-level nested EXR files were ignored.",)
    elif not direct_frames:
        frames = nested_frames

    return FrameDiscoveryResult(
        source=source_path,
        frames=frames,
        direct_frames=direct_frames,
        nested_frames=nested_frames,
        warnings=warnings,
    )
