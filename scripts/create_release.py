"""Create a source ZIP without environments, private data or EXR files."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

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
    ".pytest_cache",
    ".uv-cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "_benchmark_data",
    "generated",
    "htmlcov",
}

EXCLUDED_PREFIXES = (
    ".pytest-tmp",
    "_spike_output",
    "_ui_verification",
    "gui_",
)

EXCLUDED_SUFFIXES = {
    ".avi",
    ".docx",
    ".exr",
    ".mov",
    ".mp4",
    ".pyc",
    ".zip",
}

EXCLUDED_RELATIVE_PATHS = {
    "experiments/backend_spike_summary.md",
    "experiments/benchmark_analysis.py",
    "experiments/exr_backend_spike.py",
    "experiments/ui-preview.ini",
}


def _include(path: Path, project_root: Path) -> bool:
    relative = path.relative_to(project_root)
    if relative.as_posix() in EXCLUDED_RELATIVE_PATHS:
        return False
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if any(part.startswith(prefix) for part in relative.parts for prefix in EXCLUDED_PREFIXES):
        return False
    return path.suffix.lower() not in EXCLUDED_SUFFIXES


def release_files(project_root: Path) -> tuple[Path, ...]:
    """Return deterministic files allowed by the release policy."""

    files: list[Path] = []
    for name in ROOT_FILES:
        path = project_root / name
        if path.is_file():
            files.append(path)
    for name in ROOT_DIRECTORIES:
        directory = project_root / name
        if not directory.is_dir():
            continue
        files.extend(
            path for path in directory.rglob("*") if path.is_file() and _include(path, project_root)
        )
    return tuple(sorted(set(files), key=lambda item: item.as_posix().casefold()))


def create_release(project_root: Path, output: Path) -> tuple[Path, ...]:
    """Write a clean source archive and return its included source paths."""

    files = release_files(project_root)
    archive_root = project_root.name
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(project_root)
            archive.write(path, Path(archive_root) / relative)
    return files


def main() -> None:
    """Run the clean source-archive command-line interface."""

    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Create a clean AOVGuard release ZIP.")
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root.parent / "AOVGuard-1.2.1-source.zip",
    )
    args = parser.parse_args()

    files = create_release(project_root, args.output.resolve())
    print(f"Created: {args.output.resolve()}")
    print(f"Files: {len(files)}")


if __name__ == "__main__":
    main()
