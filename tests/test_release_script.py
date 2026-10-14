import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "aovguard_create_release",
    PROJECT_ROOT / "scripts" / "create_release.py",
)
assert SPEC is not None and SPEC.loader is not None
RELEASE_SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE_SCRIPT)
create_release = RELEASE_SCRIPT.create_release
release_files = RELEASE_SCRIPT.release_files
include_file = RELEASE_SCRIPT._include
project_version = RELEASE_SCRIPT.project_version
default_release_path = RELEASE_SCRIPT.default_release_path


def test_release_files_include_delivery_assets_and_exclude_generated_data() -> None:
    project_root = PROJECT_ROOT
    relative_files = {
        path.relative_to(project_root).as_posix() for path in release_files(project_root)
    }

    assert "README.md" in relative_files
    assert "src/aovguard/core/analysis.py" in relative_files
    assert "src/aovguard/ui_components.py" in relative_files
    assert "tests/test_core_analysis.py" in relative_files
    assert "tests/gui_process_helpers.py" in relative_files
    assert "website/index.html" in relative_files
    assert "website/assets/aovguard-current-ui.png" in relative_files
    assert "docs/sample_reports/multilayer_report.json" in relative_files
    assert "experiments/benchmark_results.json" in relative_files
    assert "experiments/benchmark_simulated_sequences.py" in relative_files
    assert "examples/.gitkeep" in relative_files
    assert "experiments/benchmark_analysis.py" not in relative_files
    assert "experiments/exr_backend_spike.py" not in relative_files
    assert "experiments/ui-preview.ini" not in relative_files
    assert not any(path.lower().endswith(".docx") for path in relative_files)
    assert not any(path.lower().endswith(".exr") for path in relative_files)
    assert not any("__pycache__" in path for path in relative_files)
    assert not any("_benchmark_data" in path for path in relative_files)


def test_release_policy_excludes_all_exrs(
    tmp_path: Path,
) -> None:
    real_example = tmp_path / "examples" / "shot.1001.exr"
    generated_example = tmp_path / "examples" / "generated" / "fixture.exr"
    retired_fixture = tmp_path / "examples" / "aovguard_multilayer_sample.exr"
    unrelated_render = tmp_path / "renders" / "shot.1001.exr"

    assert not include_file(real_example, tmp_path)
    assert not include_file(generated_example, tmp_path)
    assert not include_file(retired_fixture, tmp_path)
    assert not include_file(unrelated_render, tmp_path)


def test_release_policy_excludes_internal_word_documents(tmp_path: Path) -> None:
    academic_review = tmp_path / "docs" / "academic_review.docx"

    assert not include_file(academic_review, tmp_path)


def test_create_release_uses_one_project_root(tmp_path: Path) -> None:
    project_root = PROJECT_ROOT
    output = tmp_path / "release.zip"

    files = create_release(project_root, output)

    with ZipFile(output) as archive:
        names = archive.namelist()
    assert len(names) == len(files) + 1
    assert names
    archive_root = f"AOVGuard-{project_version(project_root)}"
    assert all(name.startswith(f"{archive_root}/") for name in names)
    assert f"{archive_root}/README.md" in names
    assert f"{archive_root}/RELEASE_MANIFEST.json" in names


def test_release_name_follows_current_project_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.8.7rc1"\n')

    assert project_version(tmp_path) == "9.8.7rc1"
    assert default_release_path(tmp_path) == tmp_path.parent / "AOVGuard-9.8.7rc1-source.zip"


@pytest.mark.parametrize("version", ["", "../../private", "1.0/secret"])
def test_release_rejects_unsafe_project_version(tmp_path: Path, version: str) -> None:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')

    with pytest.raises(ValueError, match="project.version"):
        project_version(tmp_path)


@pytest.mark.parametrize("directory", [".mypy_cache", ".ruff_cache", ".venv_verify"])
def test_release_policy_excludes_nested_caches_and_environments(
    tmp_path: Path, directory: str
) -> None:
    path = tmp_path / "scripts" / directory / "private.txt"

    assert not include_file(path, tmp_path)


def test_release_policy_does_not_follow_files_outside_project(tmp_path: Path) -> None:
    external = tmp_path / "outside.txt"
    external.write_text("private data")
    project_root = tmp_path / "project"
    project_root.mkdir()
    symlink = project_root / "README.md"
    try:
        symlink.symlink_to(external)
    except OSError:
        pytest.skip("This system does not permit unprivileged symlink creation.")

    assert symlink not in release_files(project_root)
