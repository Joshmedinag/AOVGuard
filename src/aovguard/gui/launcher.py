"""Desktop entry point that keeps Qt optional for headless installations."""

from __future__ import annotations

import sys


def main() -> int:
    """Launch the desktop UI or explain how to install its optional dependencies."""

    try:
        from aovguard.ui import main as run_ui
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".", 1)[0] in {"PySide6", "shiboken6"}:
            print(
                "The AOVGuard desktop interface requires the GUI extra. "
                "Install with: pip install 'aovguard[gui]' "
                "(source checkout: uv run --extra gui aovguard-ui).",
                file=sys.stderr,
            )
            return 1
        raise
    run_ui()
    return 0
