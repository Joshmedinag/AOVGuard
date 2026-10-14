# GitHub Workflow

The current candidate identifier is **1.4.0rc1**, prepared on 2026-10-13.
The workflow reads the project version instead of pinning a 1.3.0 wheel name.
Candidate publication and completed remote job results are separate release
evidence; this document does not claim that those jobs have completed.

The repository includes a GitHub Actions matrix configured for Windows/Linux
and Python 3.11/3.12. Each job:

1. checks out the repository;
2. installs `uv`;
3. installs its selected Python version;
4. synchronizes the lockfile with the `dev` extra, including Qt tests;
5. runs `pytest` with a 95% combined statement/branch coverage gate;
6. runs configured Ruff and mypy checks, including the source packager, wheel installer and opt-in verification scripts;
7. validates local website links and builds/verifies a source snapshot manifest;
8. builds a wheel in `dist/ci-wheel`, validates its version and installs its base
   dependencies in a separate environment;
9. verifies that the packaged CLI runs without Qt or OpenCV.

This configuration does not prove that an unpublished change has run remotely.
Local verification, commits, pushes and completed GitHub runs are recorded as
separate evidence.

The wheel check is independent of a fixed release number. It reads
`project.version` from `pyproject.toml` and requires exactly one AOVGuard wheel
in the dedicated build directory. Its filename and embedded distribution
metadata must match that version. Missing, malformed, mismatched or ambiguous
outputs fail explicitly; existing wheels in the parent `dist/` directory are
never candidates. Installation calls `uv` with an argument list and no shell,
and requests only the base wheel, leaving Qt and OpenCV out of the CLI-only
environment. The subsequent CLI smoke check confirms those imports are absent.

CI exercises temporary verifier fixtures and script type checks, not the owner's
external Maya/Venator corpus. Real-sequence runs are opt-in local checks with
explicit source/range/color intent; see `docs/real_exr_validation.md`. EXRs and
private acceptance reports are not uploaded by this workflow.

The source snapshot uses a distinct `dist/AOVGuard-ci-source.zip` destination
and refuses to overwrite an existing file. It excludes local report output,
EXRs, environments, caches and common private/temporary file patterns. Its
manifest and whole-archive SHA-256 make the selected bytes auditable, but do
not authenticate a publisher or replace source review. CI does not upload or
publish this artifact automatically.
