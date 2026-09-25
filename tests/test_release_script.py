import importlib.util
from pathlib import Path
from zipfile import ZipFile

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


def test_release_files_include_delivery_assets_and_exclude_generated_data() -> None:
    project_root = PROJECT_ROOT
    relative_files = {
        path.relative_to(project_root).as_posix() for path in release_files(project_root)
    }

    assert "README.md" in relative_files
    assert "src/aovguard/core/analysis.py" in relative_files
    assert "src/aovguard/ui_components.py" in relative_files
    assert "tests/test_core_analysis.py" in relative_files
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
    assert len(names) == len(files)
    assert names
    assert all(name.startswith(f"{project_root.name}/") for name in names)
    assert f"{project_root.name}/README.md" in names
