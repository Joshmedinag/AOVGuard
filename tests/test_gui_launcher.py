import builtins
import sys
from types import SimpleNamespace

import pytest

from aovguard.gui.launcher import main


def test_launcher_calls_gui_entrypoint(monkeypatch) -> None:
    called = []
    monkeypatch.setitem(sys.modules, "aovguard.ui", SimpleNamespace(main=lambda: called.append(True)))
    assert main() == 0
    assert called == [True]


@pytest.mark.parametrize("dependency", ["PySide6", "shiboken6"])
def test_launcher_explains_missing_optional_dependency(monkeypatch, capsys, dependency) -> None:
    original_import = builtins.__import__

    def import_without_qt(name, *args, **kwargs):
        if name == "aovguard.ui":
            raise ModuleNotFoundError("missing GUI dependency", name=dependency)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_qt)
    assert main() == 1
    assert "aovguard[gui]" in capsys.readouterr().err


def test_launcher_does_not_hide_unrelated_import_errors(monkeypatch) -> None:
    original_import = builtins.__import__

    def import_broken_gui(name, *args, **kwargs):
        if name == "aovguard.ui":
            raise ModuleNotFoundError("unexpected regression", name="aovguard.missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_broken_gui)
    with pytest.raises(ModuleNotFoundError, match="unexpected regression"):
        main()


def test_launcher_propagates_gui_exit(monkeypatch) -> None:
    def run_gui():
        raise SystemExit(7)

    monkeypatch.setitem(sys.modules, "aovguard.ui", SimpleNamespace(main=run_gui))
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 7
