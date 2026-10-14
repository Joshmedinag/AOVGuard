"""Create a source ZIP without environments, private data or EXR files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import IO, Any

ROOT_FILES = (
    ".gitignore",
    "CHANGELOG.md",
    "CITATION.cff",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "uv.lock",
)

ROOT_DIRECTORIES = (
    ".github",
    "config",
    "docs",
    "examples",
    "experiments",
    "reports",
    "scripts",
    "src",
    "tests",
    "website",
)

EXCLUDED_PARTS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "_benchmark_data",
    "generated",
    "htmlcov",
    "node_modules",
}

EXCLUDED_PREFIXES = (
    ".pytest-tmp",
    ".venv_",
    "_spike_output",
    "_ui_verification",
    ".coverage",
    ".env",
)

EXCLUDED_SUFFIXES = {
    ".avi",
    ".docx",
    ".exr",
    ".mov",
    ".mp4",
    ".pyc",
    ".zip",
    ".tmp",
    ".bak",
    ".pem",
    ".key",
}

EXCLUDED_RELATIVE_PATHS = {
    "experiments/backend_spike_summary.md",
    "experiments/benchmark_analysis.py",
    "experiments/exr_backend_spike.py",
    "experiments/ui-preview.ini",
}

MANIFEST_NAME = "RELEASE_MANIFEST.json"
MANIFEST_SCHEMA = "1.0"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
CHUNK_SIZE = 1024 * 1024


def _is_link(path: Path) -> bool:
    """Identify symlinks and Windows reparse points without following them."""

    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _include(path: Path, project_root: Path) -> bool:
    relative = path.relative_to(project_root)
    if path.is_symlink() or not path.resolve().is_relative_to(project_root.resolve()):
        return False
    return _allowed_relative(PurePosixPath(relative.as_posix()))


def _allowed_relative(relative: PurePosixPath) -> bool:
    if not relative.parts or (
        relative.as_posix() not in ROOT_FILES and relative.parts[0] not in ROOT_DIRECTORIES
    ):
        return False
    if relative.parts[0] in {"reports", "examples"} and relative.parts[1:] != (".gitkeep",):
        return False
    if relative.parts[0] == "experiments" and relative.name.casefold().startswith("gui_"):
        return False
    if relative.as_posix() in EXCLUDED_RELATIVE_PATHS:
        return False
    if any(part.casefold() in EXCLUDED_PARTS for part in relative.parts):
        return False
    if any(
        part.casefold().startswith(prefix)
        for part in relative.parts
        for prefix in EXCLUDED_PREFIXES
    ):
        return False
    return relative.suffix.lower() not in EXCLUDED_SUFFIXES


def release_files(project_root: Path) -> tuple[Path, ...]:
    """Return deterministic files allowed by the release policy."""

    files: list[Path] = []
    for name in ROOT_FILES:
        path = project_root / name
        if path.is_file() and not _is_link(path) and _include(path, project_root):
            files.append(path)
    for name in ROOT_DIRECTORIES:
        directory = project_root / name
        if not directory.is_dir() or _is_link(directory):
            continue
        # Prune before descent, including junctions and excluded/permission-denied caches.
        for current, directories, names in os.walk(directory, onerror=_raise_walk_error):
            parent = Path(current)
            directories[:] = [
                name
                for name in directories
                if not _is_link(parent / name) and _include(parent / name, project_root)
            ]
            for name in names:
                path = parent / name
                if not _is_link(path) and path.is_file() and _include(path, project_root):
                    files.append(path)
    return tuple(sorted(set(files), key=lambda item: item.as_posix().casefold()))


def _raise_walk_error(error: OSError) -> None:
    raise error


def _safe_member(name: str) -> bool:
    parts = name.split("/")
    return bool(name) and all(
        part not in {"", ".", ".."}
        and not any(character in part for character in '\\:<>"|?*')
        and not any(ord(character) < 32 for character in part)
        and not part.endswith((" ", "."))
        and part.split(".")[0].casefold()
        not in {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10)),
        }
        for part in parts
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _copy_digest(source: IO[bytes], target: IO[bytes] | None = None) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
        if target is not None:
            target.write(chunk)
    return size, digest.hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest key: {key}")
        result[key] = value
    return result


def verify_release(output: Path) -> dict[str, Any]:
    """Verify member safety, exact manifest membership and SHA-256 without extraction.

    This detects accidental corruption, not authenticity: the manifest is not
    signed. Legacy ZIPs without a manifest are deliberately not accepted.
    """

    with zipfile.ZipFile(output) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        name_set = set(names)
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Archive has duplicate or case-colliding members.")
        for member in members:
            file_type = stat.S_IFMT(member.external_attr >> 16)
            if (
                not _safe_member(member.filename)
                or member.is_dir()
                or file_type not in {0, stat.S_IFREG}
                or member.flag_bits & 1
            ):
                raise ValueError(f"Unsafe archive member: {member.filename}")
        roots = {name.split("/")[0] for name in names}
        if len(roots) != 1:
            raise ValueError("Archive must have exactly one project root.")
        root = roots.pop()
        manifest_path = f"{root}/{MANIFEST_NAME}"
        if manifest_path not in name_set:
            raise ValueError("Archive has no integrity manifest.")
        if archive.getinfo(manifest_path).file_size > 16 * CHUNK_SIZE:
            raise ValueError("Manifest exceeds the 16 MiB verification limit.")
        manifest = json.loads(archive.read(manifest_path), object_pairs_hook=_unique_object)
        if not isinstance(manifest, dict) or (
            manifest.get("schema_version") != MANIFEST_SCHEMA
            or manifest.get("artifact_kind") != "source-snapshot"
            or not isinstance(manifest.get("project_version"), str)
            or not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", manifest["project_version"])
            or root != f"AOVGuard-{manifest['project_version']}"
        ):
            raise ValueError("Invalid release manifest metadata.")
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Manifest must list source files.")
        expected = {manifest_path}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid manifest file entry.")
            relative = entry.get("path")
            size = entry.get("size")
            digest = entry.get("sha256")
            if (
                not isinstance(relative, str)
                or not _safe_member(relative)
                or not _allowed_relative(PurePosixPath(relative))
                or type(size) is not int
                or size < 0
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError("Invalid manifest file metadata.")
            name = f"{root}/{relative}"
            if name in expected or name not in name_set:
                raise ValueError(f"Duplicate or missing manifest member: {relative}")
            expected.add(name)
            if archive.getinfo(name).file_size != size:
                raise ValueError(f"Size mismatch: {relative}")
            with archive.open(name) as stream:
                actual_size, actual_digest = _copy_digest(stream)
            if actual_size != size or actual_digest != digest:
                raise ValueError(f"SHA-256 mismatch: {relative}")
        if expected != name_set:
            raise ValueError("Archive contains unlisted files.")
        metadata_path = f"{root}/pyproject.toml"
        if metadata_path not in expected:
            raise ValueError("Archive must include pyproject.toml.")
        metadata = tomllib.loads(archive.read(metadata_path).decode("utf-8"))
        project = metadata.get("project")
        if not isinstance(project, dict) or project.get("version") != manifest["project_version"]:
            raise ValueError("Manifest version does not match pyproject.toml.")
        return manifest


def project_version(project_root: Path) -> str:
    """Read the distribution version from pyproject without importing the app."""

    with (project_root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream).get("project", {})
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", version):
        raise ValueError("pyproject.toml must declare a safe, nonempty project.version.")
    return version


def default_release_path(project_root: Path) -> Path:
    """Return a versioned archive destination from the current project metadata."""

    return project_root.parent / f"AOVGuard-{project_version(project_root)}-source.zip"


def create_release(project_root: Path, output: Path) -> tuple[Path, ...]:
    """Publish a verified source snapshot without replacing an existing destination.

    Same-runtime ZIP bytes are reproducible for identical selected source bytes.
    Publication uses a same-directory hard link for atomic no-clobber behavior;
    unsupported filesystems fail instead of falling back to a destructive write.
    """

    project_root = project_root.resolve()
    output = output.absolute()
    if output.suffix.lower() != ".zip":
        raise ValueError("Source archive destination must end in .zip.")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Destination already exists; choose a new filename: {output}")
    version = project_version(project_root)
    files = release_files(project_root)
    if project_root / "pyproject.toml" not in files:
        raise ValueError("Release must include a regular pyproject.toml inside the project.")
    archive_root = f"AOVGuard-{version}"
    names = [path.relative_to(project_root).as_posix() for path in files]
    if any(not _safe_member(name) for name in names) or len(
        {name.casefold() for name in names}
    ) != len(names):
        raise ValueError("Source contains unsafe or case-colliding archive paths.")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    owned_descriptor: int | None = descriptor
    try:
        stream = os.fdopen(descriptor, "w+b")
        owned_descriptor = None
        with stream:
            entries: list[dict[str, Any]] = []
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path, relative in zip(files, names, strict=True):
                    if _is_link(path) or not _include(path, project_root):
                        raise ValueError(f"Source changed to an excluded path: {relative}")
                    with (
                        path.open("rb") as source,
                        archive.open(
                            _zip_info(f"{archive_root}/{relative}"), "w", force_zip64=True
                        ) as target,
                    ):
                        size, digest = _copy_digest(source, target)
                    entries.append({"path": relative, "size": size, "sha256": digest})
                manifest = {
                    "schema_version": MANIFEST_SCHEMA,
                    "artifact_kind": "source-snapshot",
                    "project_version": version,
                    "files": entries,
                }
                archive.writestr(
                    _zip_info(f"{archive_root}/{MANIFEST_NAME}"),
                    json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                )
            stream.flush()
            os.fsync(stream.fileno())
        verify_release(temporary)
        os.link(temporary, output)
    except BaseException as exc:
        if owned_descriptor is not None:
            try:
                os.close(owned_descriptor)
            except OSError as cleanup_error:
                exc.add_note(f"Could not close temporary descriptor: {cleanup_error}")
        try:
            temporary.unlink(missing_ok=True)
        except OSError as cleanup_error:
            exc.add_note(f"Temporary archive remains at {temporary}: {cleanup_error}")
        raise
    try:
        temporary.unlink()
    except OSError as cleanup_error:
        print(
            f"Warning: verified archive published; temporary remains at {temporary}: "
            f"{cleanup_error}",
            file=sys.stderr,
        )
    return files


def main(argv: list[str] | None = None) -> int:
    """Run the clean source-archive command-line interface."""

    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Create or verify an AOVGuard source snapshot.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Archive path; defaults to AOVGuard-<project version>-source.zip beside the checkout.",
    )
    mode.add_argument("--verify", type=Path, help="Verify an existing manifest-bearing ZIP.")
    mode.add_argument("--list", action="store_true", help="Preview selected paths without writing.")
    args = parser.parse_args(argv)

    try:
        if args.verify:
            manifest = verify_release(args.verify)
            print(f"Verified: {args.verify} ({len(manifest['files'])} source files)")
        elif args.list:
            for path in release_files(project_root):
                print(path.relative_to(project_root).as_posix())
        else:
            output = (args.output or default_release_path(project_root)).absolute()
            files = create_release(project_root, output)
            with output.open("rb") as stream:
                _, digest = _copy_digest(stream)
            print(f"Created source snapshot: {output}")
            print(f"Files: {len(files)}\nSHA-256: {digest}")
    except KeyboardInterrupt:
        print("Archive operation cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"Archive error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
