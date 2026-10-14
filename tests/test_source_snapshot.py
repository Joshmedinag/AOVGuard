from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import create_release as release


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "checkout with spaces"
    files = {
        "pyproject.toml": '[project]\nname = "aovguard"\nversion = "9.8.7rc1"\n',
        "README.md": "Snapshot with Unicode: luminancia y máscaras.\n",
        "src/aovguard/example.py": '"""Example source."""\n',
        "tests/gui_process_helpers.py": '"""Required spawn helper."""\n',
        "docs/sample_reports/approved.json": '{"anonymized": true}\n',
        "examples/.gitkeep": "",
        "reports/.gitkeep": "",
    }
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
    return root


def _archive(project: Path, tmp_path: Path) -> Path:
    output = tmp_path / "snapshot.zip"
    release.create_release(project, output)
    return output


def _rewrite(output: Path, transform) -> None:
    with zipfile.ZipFile(output) as archive:
        contents = {info.filename: archive.read(info) for info in archive.infolist()}
    transform(contents)
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def _manifest_edit(contents, edit) -> None:
    name = next(name for name in contents if name.endswith(release.MANIFEST_NAME))
    manifest = json.loads(contents[name])
    edit(manifest)
    contents[name] = json.dumps(manifest).encode()


def test_manifest_matches_exact_source_bytes(project: Path, tmp_path: Path) -> None:
    output = _archive(project, tmp_path)
    manifest = release.verify_release(output)

    assert manifest["schema_version"] == "1.0"
    assert manifest["artifact_kind"] == "source-snapshot"
    assert manifest["project_version"] == "9.8.7rc1"
    expected = {path.relative_to(project).as_posix() for path in release.release_files(project)}
    assert {entry["path"] for entry in manifest["files"]} == expected
    for entry in manifest["files"]:
        content = (project / entry["path"]).read_bytes()
        assert entry["size"] == len(content)
        assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert all(info.date_time == release.ZIP_TIMESTAMP for info in archive.infolist())
        assert all(
            stat.S_IFMT(info.external_attr >> 16) == stat.S_IFREG for info in archive.infolist()
        )


def test_snapshot_is_reproducible_across_checkout_names_and_mtimes(
    project: Path,
    tmp_path: Path,
) -> None:
    import shutil

    first = _archive(project, tmp_path)
    other = tmp_path / "other checkout"
    shutil.copytree(project, other)
    for path in release.release_files(other):
        os.utime(path, (1_700_000_000, 1_700_000_000))
    second = tmp_path / "second.zip"
    release.create_release(other, second)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize(
    "relative",
    [
        "reports/local.json",
        "reports/local.html",
        "reports/nested/private.csv",
        "examples/readme.txt",
        "examples/private.EXR",
        "config/.env.production",
        "config/token.key",
        "docs/certificate.pem",
        "src/module.tmp",
        "src/module.bak",
        "experiments/gui_private_preview.png",
        "tests/.coverage.secret",
        "scripts/.VENV_PRIVATE/secrets.txt",
        "website/node_modules/private.txt",
    ],
)
def test_snapshot_excludes_local_data(project: Path, relative: str) -> None:
    private = project / relative
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text("must not ship")
    assert private not in release.release_files(project)


def test_excluded_folders_are_pruned_before_descent(project: Path, monkeypatch) -> None:
    excluded = project / "src" / "__pycache__"
    excluded.mkdir()
    original_walk = release.os.walk
    visited = []

    def walk(*args, **kwargs):
        for current, directories, names in original_walk(*args, **kwargs):
            visited.append(Path(current))
            yield current, directories, names

    monkeypatch.setattr(release.os, "walk", walk)
    release.release_files(project)
    assert excluded not in visited


def test_windows_reparse_points_are_treated_as_links(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda _self: SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
        ),
    )
    assert release._is_link(tmp_path)


def test_linked_root_directory_is_not_traversed(project: Path, monkeypatch) -> None:
    original = release._is_link
    monkeypatch.setattr(release, "_is_link", lambda path: path == project / "src" or original(path))
    assert not any(path.is_relative_to(project / "src") for path in release.release_files(project))


def test_walk_permission_error_is_not_silent(project: Path, monkeypatch) -> None:
    def walk(_directory, *, onerror):
        onerror(PermissionError("cannot list sources"))
        return iter(())

    monkeypatch.setattr(release.os, "walk", walk)
    with pytest.raises(PermissionError, match="cannot list"):
        release.release_files(project)


def test_existing_destination_is_preserved(project: Path, tmp_path: Path) -> None:
    output = tmp_path / "existing.zip"
    output.write_bytes(b"stable artifact")
    with pytest.raises(FileExistsError, match="choose a new filename"):
        release.create_release(project, output)
    assert output.read_bytes() == b"stable artifact"
    assert not list(tmp_path.glob(".existing.zip.*.tmp"))


def test_destination_created_during_packaging_is_not_overwritten(
    project: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "racing.zip"
    original_verify = release.verify_release

    def verify(path):
        result = original_verify(path)
        output.write_bytes(b"other publisher")
        return result

    monkeypatch.setattr(release, "verify_release", verify)
    with pytest.raises(FileExistsError):
        release.create_release(project, output)
    assert output.read_bytes() == b"other publisher"
    assert not list(tmp_path.glob(".racing.zip.*.tmp"))


@pytest.mark.parametrize("stage", ["copy", "fsync", "verify", "link"])
def test_publication_failure_leaves_no_partial_archive(
    project: Path,
    tmp_path: Path,
    monkeypatch,
    stage: str,
) -> None:
    output = tmp_path / "failure.zip"

    def fail(*_args, **_kwargs):
        raise OSError("injected storage failure")

    owner, attribute = {
        "copy": (release, "_copy_digest"),
        "fsync": (release.os, "fsync"),
        "verify": (release, "verify_release"),
        "link": (release.os, "link"),
    }[stage]
    monkeypatch.setattr(owner, attribute, fail)
    with pytest.raises(OSError, match="injected storage failure"):
        release.create_release(project, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".failure.zip.*.tmp"))


def test_interrupt_removes_temporary_archive(project: Path, tmp_path: Path, monkeypatch) -> None:
    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(release, "_copy_digest", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _archive(project, tmp_path)
    assert not (tmp_path / "snapshot.zip").exists()
    assert not list(tmp_path.glob(".snapshot.zip.*.tmp"))


def test_fdopen_failure_closes_descriptor(project: Path, tmp_path: Path, monkeypatch) -> None:
    captured = []
    real_mkstemp = release.tempfile.mkstemp

    def mkstemp(**kwargs):
        descriptor, name = real_mkstemp(**kwargs)
        captured.append(descriptor)
        return descriptor, name

    def fail(*_args, **_kwargs):
        raise OSError("cannot open stream")

    monkeypatch.setattr(release.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(release.os, "fdopen", fail)
    with pytest.raises(OSError, match="cannot open stream"):
        _archive(project, tmp_path)
    with pytest.raises(OSError):
        os.fstat(captured[0])
    assert not list(tmp_path.glob(".snapshot.zip.*.tmp"))


def test_cleanup_failure_preserves_original_exception(
    project: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_copy(*_args, **_kwargs):
        raise OSError("first failure")

    def fail_unlink(*_args, **_kwargs):
        raise PermissionError("cleanup failure")

    monkeypatch.setattr(release, "_copy_digest", fail_copy)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(OSError, match="first failure") as caught:
        _archive(project, tmp_path)
    assert "Temporary archive remains" in caught.value.__notes__[0]
    assert not (tmp_path / "snapshot.zip").exists()


def test_cleanup_failure_after_publication_warns_but_keeps_verified_result(
    project: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def fail(*_args, **_kwargs):
        raise PermissionError("locked temporary")

    monkeypatch.setattr(Path, "unlink", fail)
    output = _archive(project, tmp_path)
    assert release.verify_release(output)["files"]
    assert "verified archive published; temporary remains" in capsys.readouterr().err


@pytest.mark.parametrize("suffix", [".exr", ".json", ""])
def test_archive_requires_zip_extension(project: Path, tmp_path: Path, suffix: str) -> None:
    with pytest.raises(ValueError, match="must end in .zip"):
        release.create_release(project, tmp_path / f"output{suffix}")


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "C:/escape",
        "root/../escape",
        "root//file",
        "root\\file",
        "root/file:stream",
        "root/NUL.txt",
        "root/trailing.",
        "root/tab\tfile",
        "root/trailing ",
        "root/COM1",
    ],
)
def test_unsafe_member_names_are_rejected(name: str) -> None:
    assert not release._safe_member(name)


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("alter", "mismatch"),
        ("missing", "missing"),
        ("extra", "unlisted"),
        ("no_manifest", "no integrity manifest"),
        ("traversal", "Unsafe"),
        ("absolute", "Unsafe"),
        ("case", "case-colliding"),
    ],
)
def test_verifier_rejects_inconsistent_members(
    project: Path,
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    output = _archive(project, tmp_path)

    def mutate(contents):
        readme = "AOVGuard-9.8.7rc1/README.md"
        if mutation == "alter":
            contents[readme] = b"X" * len(contents[readme])
        elif mutation == "missing":
            del contents[readme]
        elif mutation == "extra":
            contents["AOVGuard-9.8.7rc1/unlisted.txt"] = b"unlisted"
        elif mutation == "no_manifest":
            del contents[f"AOVGuard-9.8.7rc1/{release.MANIFEST_NAME}"]
        elif mutation == "traversal":
            contents["AOVGuard-9.8.7rc1/../outside.txt"] = b"unsafe"
        elif mutation == "absolute":
            contents["/outside.txt"] = b"unsafe"
        elif mutation == "case":
            contents[readme.lower()] = contents[readme]

    _rewrite(output, mutate)
    with pytest.raises(ValueError, match=message):
        release.verify_release(output)


@pytest.mark.parametrize(
    "field, value",
    [
        ("schema_version", "99"),
        ("artifact_kind", "release"),
        ("project_version", None),
        ("project_version", "1.2.3"),
        ("files", {}),
        ("files", []),
        ("files", [None]),
        ("files", [{"path": "README.md", "size": True, "sha256": "0" * 64}]),
        ("files", [{"path": "README.md", "size": -1, "sha256": "0" * 64}]),
        ("files", [{"path": "README.md", "size": 1, "sha256": "invalid"}]),
        ("files", [{"path": "reports/private.json", "size": 0, "sha256": "0" * 64}]),
    ],
)
def test_verifier_rejects_invalid_manifest(
    project: Path,
    tmp_path: Path,
    field: str,
    value,
) -> None:
    output = _archive(project, tmp_path)
    _rewrite(
        output,
        lambda contents: _manifest_edit(
            contents,
            lambda manifest: manifest.update({field: value}),
        ),
    )
    with pytest.raises(ValueError):
        release.verify_release(output)


def test_verifier_rejects_duplicate_manifest_keys(project: Path, tmp_path: Path) -> None:
    output = _archive(project, tmp_path)

    def mutate(contents):
        key = f"AOVGuard-9.8.7rc1/{release.MANIFEST_NAME}"
        contents[key] = contents[key].replace(b"{", b'{"schema_version": "1.0",', 1)

    _rewrite(output, mutate)
    with pytest.raises(ValueError, match="Duplicate manifest key"):
        release.verify_release(output)


def test_verifier_rejects_symlink_members(project: Path, tmp_path: Path) -> None:
    output = _archive(project, tmp_path)
    with zipfile.ZipFile(output, "a") as archive:
        info = zipfile.ZipInfo("AOVGuard-9.8.7rc1/docs/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../outside")
    with pytest.raises(ValueError, match="Unsafe archive member"):
        release.verify_release(output)


def test_verifier_compares_manifest_version_with_archived_metadata(
    project: Path,
    tmp_path: Path,
) -> None:
    output = _archive(project, tmp_path)

    def mutate(contents):
        payload = b'[project]\nversion = "2.0.0"\n'
        contents["AOVGuard-9.8.7rc1/pyproject.toml"] = payload

        def edit(manifest):
            entry = next(entry for entry in manifest["files"] if entry["path"] == "pyproject.toml")
            entry.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())

        _manifest_edit(contents, edit)

    _rewrite(output, mutate)
    with pytest.raises(ValueError, match="version does not match"):
        release.verify_release(output)


def test_cli_list_is_read_only(project: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(release, "__file__", str(project / "scripts" / "create_release.py"))
    assert release.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "tests/gui_process_helpers.py" in output
    assert not list(project.parent.glob("*.zip"))


def test_cli_create_verify_and_refuse_overwrite(
    project: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(release, "__file__", str(project / "scripts" / "create_release.py"))
    output = tmp_path / "cli.zip"
    assert release.main(["--output", str(output)]) == 0
    assert "SHA-256:" in capsys.readouterr().out
    assert release.main(["--verify", str(output)]) == 0
    assert "Verified:" in capsys.readouterr().out
    assert release.main(["--output", str(output)]) == 1
    assert "already exists" in capsys.readouterr().err


def test_cli_invalid_zip_and_interrupt_exit_codes(tmp_path: Path, monkeypatch, capsys) -> None:
    output = tmp_path / "broken.zip"
    output.write_bytes(b"not a ZIP")
    assert release.main(["--verify", str(output)]) == 1
    assert "Traceback" not in capsys.readouterr().err

    def interrupt(_path):
        raise KeyboardInterrupt

    monkeypatch.setattr(release, "verify_release", interrupt)
    assert release.main(["--verify", str(output)]) == 130
    assert "cancelled" in capsys.readouterr().err


def test_verifier_runs_with_only_standard_library(project: Path, tmp_path: Path) -> None:
    output = _archive(project, tmp_path)
    command = [
        sys.executable,
        "-I",
        "-S",
        str(Path(release.__file__).resolve()),
        "--verify",
        str(output),
    ]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Verified:" in result.stdout


@pytest.mark.parametrize("extra", [None, "second/file.txt"])
def test_verifier_requires_one_root(tmp_path: Path, extra: str | None) -> None:
    output = tmp_path / "roots.zip"
    with zipfile.ZipFile(output, "w") as archive:
        if extra is not None:
            archive.writestr("first/file.txt", "first")
            archive.writestr(extra, "second")
    with pytest.raises(ValueError, match="exactly one project root"):
        release.verify_release(output)


def test_verifier_limits_manifest_size(project: Path, tmp_path: Path, monkeypatch) -> None:
    output = _archive(project, tmp_path)
    original = zipfile.ZipFile.getinfo

    def getinfo(self, name):
        info = original(self, name)
        if name.endswith(release.MANIFEST_NAME):
            info.file_size = 16 * release.CHUNK_SIZE + 1
        return info

    monkeypatch.setattr(zipfile.ZipFile, "getinfo", getinfo)
    with pytest.raises(ValueError, match="16 MiB"):
        release.verify_release(output)


def test_verifier_checks_recorded_size(project: Path, tmp_path: Path) -> None:
    output = _archive(project, tmp_path)
    _rewrite(
        output,
        lambda contents: _manifest_edit(
            contents,
            lambda manifest: manifest["files"][0].update(size=999),
        ),
    )
    with pytest.raises(ValueError, match="Size mismatch"):
        release.verify_release(output)


def test_verifier_requires_project_metadata(project: Path, tmp_path: Path) -> None:
    output = _archive(project, tmp_path)

    def mutate(contents):
        del contents["AOVGuard-9.8.7rc1/pyproject.toml"]
        _manifest_edit(
            contents,
            lambda manifest: manifest.update(
                files=[entry for entry in manifest["files"] if entry["path"] != "pyproject.toml"]
            ),
        )

    _rewrite(output, mutate)
    with pytest.raises(ValueError, match="must include pyproject.toml"):
        release.verify_release(output)


def test_source_metadata_must_be_a_table(project: Path) -> None:
    (project / "pyproject.toml").write_text('project = "not a table"\n')
    with pytest.raises(ValueError, match="project.version"):
        release.project_version(project)


def test_excluded_metadata_cannot_be_packaged(project: Path, tmp_path: Path, monkeypatch) -> None:
    original = release._is_link
    monkeypatch.setattr(
        release, "_is_link", lambda path: path.name == "pyproject.toml" or original(path)
    )
    with pytest.raises(ValueError, match="must include a regular pyproject.toml"):
        _archive(project, tmp_path)


def test_case_colliding_source_paths_cannot_be_packaged(
    project: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        release,
        "release_files",
        lambda root: (
            root / "pyproject.toml",
            root / "README.md",
            root / "readme.md",
        ),
    )
    with pytest.raises(ValueError, match="case-colliding archive paths"):
        _archive(project, tmp_path)


def test_source_revalidated_before_copy(project: Path, tmp_path: Path, monkeypatch) -> None:
    files = release.release_files(project)
    monkeypatch.setattr(release, "release_files", lambda _root: files)
    monkeypatch.setattr(release, "_is_link", lambda _path: True)
    with pytest.raises(ValueError, match="changed to an excluded path"):
        _archive(project, tmp_path)
    assert not (tmp_path / "snapshot.zip").exists()
    assert not list(tmp_path.glob(".snapshot.zip.*.tmp"))


def test_failed_descriptor_cleanup_keeps_primary_error(
    project: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    close = release.os.close

    def fail_fdopen(*_args, **_kwargs):
        raise OSError("original fdopen error")

    def fail_close(descriptor):
        close(descriptor)
        raise OSError("descriptor close error")

    monkeypatch.setattr(release.os, "fdopen", fail_fdopen)
    monkeypatch.setattr(release.os, "close", fail_close)
    with pytest.raises(OSError, match="original fdopen error") as caught:
        _archive(project, tmp_path)
    assert "Could not close temporary descriptor" in caught.value.__notes__[0]


def test_release_policy_excludes_unknown_root(project: Path) -> None:
    assert not release._include(project / "private" / "notes.txt", project)
