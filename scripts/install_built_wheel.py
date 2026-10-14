"""Validate and install the single current AOVGuard wheel in an explicit directory."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path


def _project_metadata(pyproject: Path) -> tuple[str, str]:
    """Read the expected distribution and canonical version from project metadata."""

    with pyproject.open("rb") as handle:
        project = tomllib.load(handle).get("project")
    if not isinstance(project, dict) or project.get("name") != "aovguard":
        raise ValueError("pyproject.toml must declare project.name = 'aovguard'.")
    version = project.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9][0-9A-Za-z.+!]*", version):
        raise ValueError("pyproject.toml must declare a nonempty canonical project.version.")
    return "aovguard", version


def _validate_wheel(path: Path, distribution: str, version: str) -> None:
    """Match the wheel filename and embedded metadata before running an installer."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Wheel must be a regular, non-symlink file: {path}")
    fields = path.name[:-4].split("-")
    if (
        path.suffix != ".whl"
        or len(fields) not in {5, 6}
        or fields[0].casefold() != distribution
        or any(not field or not re.fullmatch(r"[A-Za-z0-9_.+!]+", field) for field in fields)
        or (len(fields) == 6 and not re.fullmatch(r"[0-9][A-Za-z0-9_]*", fields[2]))
    ):
        raise ValueError(f"Invalid AOVGuard wheel filename: {path.name}")
    if fields[1] != version:
        raise ValueError(
            f"Wheel filename version {fields[1]!r} does not match project.version {version!r}."
        )
    expected_info = f"{fields[0]}-{fields[1]}.dist-info"
    with zipfile.ZipFile(path) as archive:
        metadata_members = [
            member
            for member in archive.infolist()
            if member.filename.endswith(".dist-info/METADATA")
        ]
        wheel_members = [
            member for member in archive.infolist() if member.filename.endswith(".dist-info/WHEEL")
        ]
        if (
            len(metadata_members) != 1
            or metadata_members[0].filename != f"{expected_info}/METADATA"
            or len(wheel_members) != 1
            or wheel_members[0].filename != f"{expected_info}/WHEEL"
        ):
            raise ValueError("Wheel must contain exactly one matching METADATA and WHEEL record.")
        if metadata_members[0].file_size > 1024 * 1024:
            raise ValueError("Wheel METADATA exceeds the 1 MiB validation limit.")
        message = BytesParser(policy=policy.default).parsebytes(archive.read(metadata_members[0]))
        names = message.get_all("Name", [])
        versions = message.get_all("Version", [])
        if (
            len(names) != 1
            or str(names[0]).casefold() != distribution
            or len(versions) != 1
            or str(versions[0]) != version
        ):
            raise ValueError("Wheel embedded Name/Version does not match pyproject.toml.")
        damaged_member = archive.testzip()
        if damaged_member is not None:
            raise ValueError(f"Wheel CRC validation failed: {damaged_member}")


def select_built_wheel(wheel_directory: Path, pyproject: Path) -> Path:
    """Require one AOVGuard wheel in the supplied directory, with the current version.

    The function never searches parent folders or chooses the newest filename.
    Multiple AOVGuard wheels, including stale versions, are an explicit error.
    Other distributions are ignored and cannot substitute for AOVGuard.
    """

    distribution, version = _project_metadata(pyproject)
    directory = wheel_directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError(f"Wheel directory is not a directory: {directory}")
    candidates = sorted(
        (
            path
            for path in directory.iterdir()
            if path.suffix.casefold() == ".whl"
            and path.name.split("-", 1)[0].casefold() == distribution
        ),
        key=lambda path: path.name.casefold(),
    )
    if len(candidates) != 1:
        raise ValueError(
            f"Expected exactly one AOVGuard wheel in {directory}; found {len(candidates)}."
        )
    wheel = candidates[0]
    _validate_wheel(wheel, distribution, version)
    return wheel


def install_built_wheel(
    wheel_directory: Path,
    pyproject: Path,
    python: str,
    *,
    uv: str = "uv",
) -> Path:
    """Install the validated base wheel using uv argument vectors without a shell."""

    wheel = select_built_wheel(wheel_directory, pyproject)
    subprocess.run(
        [uv, "pip", "install", "--python", python, str(wheel)],
        check=True,
        shell=False,
    )
    return wheel


def main(argv: list[str] | None = None) -> int:
    """Run version-independent base-wheel validation and installation for CI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument(
        "--python", required=True, help="Target Python interpreter or uv environment."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "pyproject.toml",
        help="Project metadata used to verify the built distribution version.",
    )
    parser.add_argument("--uv", default="uv", help="uv executable; passed without shell expansion.")
    args = parser.parse_args(argv)
    try:
        wheel = install_built_wheel(args.wheel_dir, args.project, args.python, uv=args.uv)
    except KeyboardInterrupt:
        print("Wheel installation cancelled.", file=sys.stderr)
        return 130
    except subprocess.CalledProcessError as exc:
        print(f"Wheel installation failed: uv exited with code {exc.returncode}.", file=sys.stderr)
        return exc.returncode if exc.returncode > 0 else 1
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"Wheel validation/installation error: {exc}", file=sys.stderr)
        return 1
    print(f"Installed verified base wheel: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
