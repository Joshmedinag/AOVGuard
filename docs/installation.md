# Installation

## Requirements

AOVGuard requires:

- Python 3.11 or 3.12
- `uv` for repeatable installation
- macOS, Linux, or Windows with the required Python packages available

## Recommended setup with `uv`

From the project root, where `pyproject.toml` is located:

```bash
uv python install 3.12
uv sync --python 3.12 --extra dev
```

Run the test suite:

```bash
uv run pytest
```

Open the UI:

```bash
uv run aovguard-ui
```

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
