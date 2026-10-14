# Installation

These commands target the **1.4.0rc1 prerelease** prepared on 2026-10-13.
It consolidates the development updates after stable 1.3.0. Candidate packages
must retain their `rc1` identifier; the historical 1.3.0 verification below
does not substitute for candidate clean-install or remote-CI evidence. See
[candidate release notes](release_notes_1.4.0rc1.md).

## Requirements

AOVGuard requires:

- Python 3.11 or 3.12
- `uv` for repeatable installation
- OpenEXR 3.3 or newer, matching the modern `OpenEXR.File` reader API
- macOS, Linux, or Windows with the required Python packages available

The CI matrix is configured for Windows and Linux with Python 3.11 and 3.12.
macOS is not included in that matrix. Base runtime dependencies are NumPy and
OpenEXR; neither the CLI nor the legacy analyzers require OpenCV or Qt.

## Recommended setup with `uv`

From the project root, where `pyproject.toml` is located:

```bash
uv python install 3.12
uv sync --locked --python 3.12
```

The base environment supports CLI inspection and analysis. Desktop use is an
optional extra:

```bash
uv run --extra gui aovguard-ui
```

The candidate includes memory-admission and isolated-execution options;
existing 1.3.0 artifacts predate both. Canonical CLI
analysis and the GUI isolate frame work by default, without requiring Qt in
the child or in CLI-only installations. No external worker service is needed.
Use `--frame-timeout-seconds 60` to add a frame service deadline, or deliberately
choose `--in-process` when native-I/O cancellation is not required. See
`usage.md` for deadline, API opt-in and cleanup semantics.

For development and the complete Qt-inclusive test suite, synchronize the
`dev` extra, which includes PySide6 and development tools:

```bash
uv sync --locked --extra dev
```

Run the test suite:

```bash
uv run --locked --extra dev pytest
```

Open the UI:

```bash
uv run --extra gui aovguard-ui
```

Run the same development quality gates as CI:

```bash
uv run --locked --extra dev ruff check src tests scripts experiments/benchmark_simulated_sequences.py experiments/benchmark_memory.py
uv run --locked --extra dev mypy src/aovguard scripts/create_release.py scripts/install_built_wheel.py scripts/verification_memory.py scripts/verify_real_sequence.py scripts/verify_gui_sequence.py
```

Qt tests run without a visible desktop when `QT_QPA_PLATFORM=offscreen` is set.
OpenCV and its EXR-codec environment switch are no longer needed. Pytest adds
the checkout root to its import path, so direct `pytest` and `python -m pytest`
both resolve the developer-only benchmark module.

## Install a distribution wheel

Build this checkout into a separate candidate directory:

```bash
uv build --wheel --out-dir dist/rc-wheel
```

For a CLI-only installation:

```bash
python -m pip install ./dist/rc-wheel/aovguard-1.4.0rc1-py3-none-any.whl
aovguard --help
```

To include the optional desktop interface:

```bash
python -m pip install "./dist/rc-wheel/aovguard-1.4.0rc1-py3-none-any.whl[gui]"
aovguard-ui
```

The launcher reports how to install `aovguard[gui]` if Qt is missing, without
requiring Qt for unrelated CLI commands. Build local artifacts using the
dedicated directory above and create a source archive with
`uv run python scripts/create_release.py`;
the default archive name follows the version in `pyproject.toml`. Development
archives refuse to overwrite existing destinations; use a separate filename
for each source snapshot. This candidate does not imply a PyPI publication;
the examples install a local wheel.

To verify version-independent wheel selection in a fresh CLI-only environment:

```bash
uv venv .venv_rc_cli --python 3.12
uv run --locked python scripts/install_built_wheel.py --wheel-dir dist/rc-wheel --python .venv_rc_cli
uv run --no-project --python .venv_rc_cli python -c "import importlib.util; from aovguard.cli import main; assert importlib.util.find_spec('PySide6') is None; assert importlib.util.find_spec('cv2') is None; main(['--help'])"
```

The helper requires one AOVGuard wheel matching `pyproject.toml`, including
embedded metadata. It does not select old wheels in the parent `dist/` folder
or silently choose the newest of several candidates. If installing a downloaded
wheel without a checkout, use the direct pip command with its actual location.

Local verification for 1.3.0 on 2026-10-12 used Windows/Python 3.11.14 and
3.12.12: each run had 434 passed, one Windows symlink-permission check skipped, and combined
statement/branch coverage was 95.56%. A fresh base-wheel environment passed CLI
help and real EXR inspection/analysis without Qt/OpenCV. These local results do
not assert that Linux or remote CI has run the same candidate.

## Verify a source snapshot

The development packager uses only the Python standard library. Preview its
file selection, create a new ZIP and verify its embedded SHA-256 manifest:

```powershell
python scripts/create_release.py --list
python scripts/create_release.py --output dist/AOVGuard-1.4.0rc1-source.zip
python scripts/create_release.py --verify dist/AOVGuard-1.4.0rc1-source.zip
```

Verification checks safe member names, exact manifest membership, sizes, hashes
and the version in the included `pyproject.toml`; it does not extract or execute
the archive. A manifest is not a signature. Review the source files for private
content before distributing them, and verify an independently trusted overall
checksum when receiving a ZIP from someone else.

The archive contains one `AOVGuard-<version>/` folder. Extract your verified
snapshot into a new empty directory, enter that folder, then run:

```powershell
uv sync --locked --python 3.12 --extra dev
uv run --locked --extra dev pytest --cov-fail-under=95
uv run --locked --extra dev aovguard --help
uv run --locked --extra dev python scripts/validate_website.py
```

The output directory must support hard links for atomic no-overwrite publication;
use local NTFS if a network or removable drive refuses this operation, then copy
the completed ZIP and run `--verify` on that copy. Existing 1.3.0 archives do not
have a manifest and are not accepted by this new verifier. Do not relabel an
candidate or development snapshot as the stable 1.3.0 download.

## Alternative editable install

If you are not using `uv`, create a virtual environment and install the project in editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

On Windows, activate the virtual environment with:

```powershell
.venv\Scripts\activate
```
