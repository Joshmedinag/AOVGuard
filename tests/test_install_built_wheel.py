from __future__ import annotations

import re
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import install_built_wheel as installer


@pytest.fixture
def build(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    pyproject = root / "pyproject.toml"
    pyproject.write_text('[project]\nname = "aovguard"\nversion = "9.8.7rc1"\n')
    wheel_dir = root / "dist" / "current wheel"
    wheel_dir.mkdir(parents=True)
    return wheel_dir, pyproject


def make_wheel(
    directory: Path,
    *,
    filename: str = "aovguard-9.8.7rc1-py3-none-any.whl",
    version: str = "9.8.7rc1",
    name: str = "aovguard",
    metadata: str | None = None,
    info_directory: str | None = None,
    with_wheel: bool = True,
) -> Path:
    path = directory / filename
    info = info_directory or f"aovguard-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{info}/METADATA",
            metadata or f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n",
        )
        if with_wheel:
            archive.writestr(
                f"{info}/WHEEL",
                "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            )
        archive.writestr("aovguard/example.py", '"""Wheel fixture."""\n')
    return path


@pytest.mark.parametrize("version", ["1.3.0", "9.8.7rc1", "2.0.0", "2.1.0.post1", "2.0.0+build.4"])
def test_selection_follows_project_version(build: tuple[Path, Path], version: str) -> None:
    directory, pyproject = build
    pyproject.write_text(f'[project]\nname = "aovguard"\nversion = "{version}"\n')
    wheel = make_wheel(directory, filename=f"aovguard-{version}-py3-none-any.whl", version=version)

    assert installer.select_built_wheel(directory, pyproject) == wheel.resolve()


def test_one_build_tagged_wheel_is_valid(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    wheel = make_wheel(directory, filename="aovguard-9.8.7rc1-2-py3-none-any.whl")

    assert installer.select_built_wheel(directory, pyproject) == wheel


def test_stable_wheel_in_parent_dist_is_not_a_candidate(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    stale = make_wheel(
        directory.parent, filename="aovguard-1.3.0-py3-none-any.whl", version="1.3.0"
    )
    current = make_wheel(directory)

    assert installer.select_built_wheel(directory, pyproject) == current
    assert stale.is_file()


def test_selection_does_not_fall_back_to_parent_or_subdirectories(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    make_wheel(directory.parent)
    nested = directory / "nested"
    nested.mkdir()
    make_wheel(nested)

    with pytest.raises(ValueError, match="exactly one.*found 0"):
        installer.select_built_wheel(directory, pyproject)


def test_unrelated_distribution_cannot_substitute_for_aovguard(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    make_wheel(directory, filename="different-9.8.7rc1-py3-none-any.whl", name="different")

    with pytest.raises(ValueError, match="found 0"):
        installer.select_built_wheel(directory, pyproject)
    current = make_wheel(directory)
    assert installer.select_built_wheel(directory, pyproject) == current


@pytest.mark.parametrize("second_version", ["9.8.7rc1", "1.3.0"])
def test_multiple_wheels_fail_instead_of_selecting_newest(
    build: tuple[Path, Path],
    second_version: str,
) -> None:
    directory, pyproject = build
    make_wheel(directory)
    make_wheel(
        directory,
        filename=f"aovguard-{second_version}-2-py3-none-any.whl",
        version=second_version,
    )

    with pytest.raises(ValueError, match="exactly one.*found 2"):
        installer.select_built_wheel(directory, pyproject)


def test_single_stale_version_fails(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    make_wheel(directory, filename="aovguard-1.3.0-py3-none-any.whl", version="1.3.0")

    with pytest.raises(ValueError, match="filename version.*project.version"):
        installer.select_built_wheel(directory, pyproject)


@pytest.mark.parametrize(
    "filename",
    [
        "aovguard-9.8.7rc1.whl",
        "aovguard-9.8.7rc1-py3-none-any-extra.whl",
        "aovguard-9.8.7rc1-bad-py3-none-any.whl",
        "aovguard-9.8.7rc1-py3--any.whl",
        "aovguard-9.8.7rc1-py3-none-any.WHL",
    ],
)
def test_invalid_wheel_filename_fails(build: tuple[Path, Path], filename: str) -> None:
    directory, pyproject = build
    make_wheel(directory, filename=filename)

    with pytest.raises(ValueError, match="Invalid.*filename"):
        installer.select_built_wheel(directory, pyproject)


@pytest.mark.parametrize(
    "metadata",
    [
        "Name: different\nVersion: 9.8.7rc1\n",
        "Name: aovguard\nVersion: 1.3.0\n",
        "Version: 9.8.7rc1\n",
        "Name: aovguard\n",
        "Name: aovguard\nName: aovguard\nVersion: 9.8.7rc1\n",
        "Name: aovguard\nVersion: 9.8.7rc1\nVersion: 9.8.7rc1\n",
    ],
)
def test_embedded_metadata_must_match_project_exactly(
    build: tuple[Path, Path],
    metadata: str,
) -> None:
    directory, pyproject = build
    make_wheel(directory, metadata=metadata)

    with pytest.raises(ValueError, match="embedded Name/Version"):
        installer.select_built_wheel(directory, pyproject)


@pytest.mark.parametrize(
    "change", ["missing_metadata", "missing_wheel", "second_metadata", "wrong_info"]
)
def test_missing_or_ambiguous_distribution_records_fail(
    build: tuple[Path, Path],
    change: str,
) -> None:
    directory, pyproject = build
    if change == "wrong_info":
        make_wheel(directory, info_directory="different-9.8.7rc1.dist-info")
    elif change == "missing_wheel":
        make_wheel(directory, with_wheel=False)
    else:
        path = directory / "aovguard-9.8.7rc1-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("aovguard-9.8.7rc1.dist-info/WHEEL", "Wheel-Version: 1.0\n")
            if change == "second_metadata":
                archive.writestr(
                    "aovguard-9.8.7rc1.dist-info/METADATA", "Name: aovguard\nVersion: 9.8.7rc1\n"
                )
                archive.writestr(
                    "different-9.8.7rc1.dist-info/METADATA", "Name: different\nVersion: 9.8.7rc1\n"
                )

    with pytest.raises(ValueError, match="exactly one matching METADATA and WHEEL"):
        installer.select_built_wheel(directory, pyproject)


def test_invalid_zip_is_not_passed_to_installer(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    (directory / "aovguard-9.8.7rc1-py3-none-any.whl").write_bytes(b"not a ZIP archive")

    with pytest.raises(zipfile.BadZipFile):
        installer.select_built_wheel(directory, pyproject)


def test_damaged_payload_crc_is_detected(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    path = make_wheel(directory)
    with zipfile.ZipFile(path) as archive:
        member = archive.getinfo("aovguard/example.py")
    data = bytearray(path.read_bytes())
    filename_length, extra_length = struct.unpack_from("<HH", data, member.header_offset + 26)
    data[member.header_offset + 30 + filename_length + extra_length] ^= 1
    path.write_bytes(data)

    with pytest.raises(ValueError, match="CRC validation failed"):
        installer.select_built_wheel(directory, pyproject)


def test_oversized_metadata_is_rejected(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    make_wheel(directory, metadata="x" * (1024 * 1024 + 1))

    with pytest.raises(ValueError, match="1 MiB"):
        installer.select_built_wheel(directory, pyproject)


def test_wheel_directory_entry_is_not_a_regular_wheel(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    (directory / "aovguard-9.8.7rc1-py3-none-any.whl").mkdir()

    with pytest.raises(ValueError, match="regular, non-symlink"):
        installer.select_built_wheel(directory, pyproject)


def test_symlink_wheel_is_rejected_without_requiring_link_privileges(
    build: tuple[Path, Path],
    monkeypatch,
) -> None:
    directory, pyproject = build
    wheel = make_wheel(directory)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == wheel or original(path))

    with pytest.raises(ValueError, match="regular, non-symlink"):
        installer.select_built_wheel(directory, pyproject)


@pytest.mark.parametrize(
    "text",
    [
        "",
        '[project]\nname = "different"\nversion = "9.8.7rc1"\n',
        '[project]\nname = "aovguard"\n',
        '[project]\nname = "aovguard"\nversion = true\n',
        '[project]\nname = "aovguard"\nversion = ""\n',
        '[project]\nname = "aovguard"\nversion = "../../old"\n',
    ],
)
def test_invalid_project_metadata_fails(build: tuple[Path, Path], text: str) -> None:
    directory, pyproject = build
    pyproject.write_text(text)

    with pytest.raises(ValueError, match="pyproject.toml"):
        installer.select_built_wheel(directory, pyproject)


def test_missing_build_directory_fails_without_searching_dist(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    make_wheel(directory)

    with pytest.raises(FileNotFoundError):
        installer.select_built_wheel(directory / "absent", pyproject)


def test_build_directory_must_be_a_directory(build: tuple[Path, Path]) -> None:
    directory, pyproject = build
    wheel = make_wheel(directory)

    with pytest.raises(ValueError, match="not a directory"):
        installer.select_built_wheel(wheel, pyproject)


def test_install_uses_argument_vector_without_shell_or_gui_extra(
    build: tuple[Path, Path],
    monkeypatch,
) -> None:
    directory, pyproject = build
    wheel = make_wheel(directory)
    calls = []
    monkeypatch.setattr(
        installer.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    selected = installer.install_built_wheel(
        directory,
        pyproject,
        "interpreter with spaces; literal",
        uv="uv executable with spaces",
    )

    assert selected == wheel
    assert calls == [
        (
            (
                [
                    "uv executable with spaces",
                    "pip",
                    "install",
                    "--python",
                    "interpreter with spaces; literal",
                    str(wheel),
                ],
            ),
            {"check": True, "shell": False},
        )
    ]
    assert "[gui]" not in calls[0][0][0][-1]


def test_main_invalid_output_never_runs_uv(build: tuple[Path, Path], monkeypatch, capsys) -> None:
    directory, pyproject = build
    monkeypatch.setattr(
        installer.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("uv must not run")
    )

    assert (
        installer.main(
            [
                "--wheel-dir",
                str(directory),
                "--project",
                str(pyproject),
                "--python",
                "target",
            ]
        )
        == 1
    )
    assert "found 0" in capsys.readouterr().err


@pytest.mark.parametrize(
    "archive_error", [zipfile.BadZipFile("invalid ZIP"), RuntimeError("unsupported compression")]
)
def test_main_invalid_archive_reports_clear_error_before_installation(
    build: tuple[Path, Path],
    monkeypatch,
    capsys,
    archive_error: Exception,
) -> None:
    directory, pyproject = build
    make_wheel(directory)

    def reject(*_args, **_kwargs):
        raise archive_error

    monkeypatch.setattr(installer, "_validate_wheel", reject)
    monkeypatch.setattr(
        installer.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("uv must not run")
    )
    assert (
        installer.main(
            [
                "--wheel-dir",
                str(directory),
                "--project",
                str(pyproject),
                "--python",
                "target",
            ]
        )
        == 1
    )
    assert str(archive_error) in capsys.readouterr().err


@pytest.mark.parametrize(
    "failure,expected",
    [
        (FileNotFoundError("uv absent"), 1),
        (subprocess.CalledProcessError(7, "uv"), 7),
        (subprocess.CalledProcessError(-9, "uv"), 1),
        (KeyboardInterrupt(), 130),
    ],
)
def test_main_reports_installation_failure(
    build: tuple[Path, Path],
    monkeypatch,
    capsys,
    failure: BaseException,
    expected: int,
) -> None:
    directory, pyproject = build
    make_wheel(directory)

    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(installer.subprocess, "run", fail)
    assert (
        installer.main(
            [
                "--wheel-dir",
                str(directory),
                "--project",
                str(pyproject),
                "--python",
                "target",
            ]
        )
        == expected
    )
    assert capsys.readouterr().err


def test_main_success_installs_current_base_wheel(
    build: tuple[Path, Path], monkeypatch, capsys
) -> None:
    directory, pyproject = build
    wheel = make_wheel(directory)
    monkeypatch.setattr(installer.subprocess, "run", lambda *_args, **_kwargs: None)

    assert (
        installer.main(
            [
                "--wheel-dir",
                str(directory),
                "--project",
                str(pyproject),
                "--python",
                "target",
            ]
        )
        == 0
    )
    assert wheel.name in capsys.readouterr().out


def test_ci_build_and_install_share_dedicated_directory_without_version_pin() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    ).read_text()
    build_directory = re.search(r"uv build --wheel --out-dir (\S+)", workflow)
    install_directory = re.search(r"install_built_wheel\.py --wheel-dir (\S+)", workflow)

    assert build_directory is not None and install_directory is not None
    assert build_directory.group(1) == install_directory.group(1)
    assert build_directory.group(1) != "dist"
    assert not re.search(r"uv pip install.*aovguard-[0-9].*\.whl", workflow)
    assert "scripts/install_built_wheel.py" in workflow
