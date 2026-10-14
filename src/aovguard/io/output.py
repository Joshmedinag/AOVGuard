"""Validated, atomic report publication on the destination filesystem."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO


def _same_file(first: Path, second: Path) -> bool:
    if first.resolve() == second.resolve():
        return True
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False


def validate_output_paths(
    outputs: Iterable[str | Path],
    *,
    protected_paths: Iterable[str | Path] = (),
) -> None:
    """Reject EXR targets, links, non-files, input aliases and duplicate outputs.

    Resolve lexical/symlink aliases and check hard links where files exist.
    Permission/stat failures propagate instead of silently bypassing checks.
    This is accidental-overwrite protection, not a concurrent-filesystem lock.
    """

    protected = tuple(Path(path) for path in protected_paths)
    checked: list[Path] = []
    for value in outputs:
        path = Path(value)
        if path.suffix.casefold() == ".exr":
            raise ValueError(f"Report destination must not be an EXR file: {path}")
        if path.is_symlink():
            raise ValueError(f"Report destination must not be a symbolic link: {path}")
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None:
            if not stat.S_ISREG(mode):
                raise ValueError(f"Report destination must be a regular file: {path}")
            if not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                raise PermissionError(f"Report destination is read-only: {path}")
        for input_path in protected:
            if _same_file(path, input_path):
                raise ValueError(f"Report destination would overwrite an input file: {input_path}")
        for previous in checked:
            if _same_file(path, previous):
                raise ValueError(f"Report destinations must be different files: {previous}, {path}")
        checked.append(path)


@contextmanager
def atomic_text_writer(
    output_path: str | Path,
    *,
    protected_paths: Iterable[str | Path] = (),
) -> Iterator[TextIO]:
    """Publish UTF-8 text only after writing, flushing and syncing a sibling temp.

    Failures before replacement (including Ctrl+C) leave the existing target
    intact and attempt cleanup without masking the original exception.
    Replacement is per file, not a multi-report transaction or a power-loss
    durability guarantee. Callers must supply any additional input paths.
    """

    path = Path(output_path).absolute()
    protected = tuple(Path(value).absolute() for value in protected_paths)
    validate_output_paths((path,), protected_paths=protected)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    owned_descriptor: int | None = descriptor
    try:
        stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="")
        owned_descriptor = None
        with stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        # Recheck before replacing in case a destination was changed while
        # serializing; another process can still race the final rename.
        validate_output_paths((path,), protected_paths=protected)
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            pass
        else:
            temporary.chmod(stat.S_IMODE(mode))
        os.replace(temporary, path)
    except BaseException as exc:
        if owned_descriptor is not None:
            try:
                os.close(owned_descriptor)
            except OSError as cleanup_error:
                exc.add_note(f"Could not close temporary descriptor: {cleanup_error}")
        try:
            temporary.unlink(missing_ok=True)
        except OSError as cleanup_error:
            exc.add_note(f"Temporary report remains at {temporary}: {cleanup_error}")
        raise
