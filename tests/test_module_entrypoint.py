from __future__ import annotations

import runpy
import sys
from pathlib import Path


def test_module_entrypoint_invokes_main_and_exits(monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    import importlib

    import impliforge

    main_module = importlib.import_module("impliforge.main")

    calls: list[str] = []

    def fake_main() -> int:
        calls.append("called")
        return 7

    monkeypatch.setattr(main_module, "main", fake_main)
    monkeypatch.setattr(impliforge, "main", fake_main)

    try:
        runpy.run_module("impliforge", run_name="__main__")
        raise AssertionError("Expected SystemExit to be raised")
    except SystemExit as exc:
        assert exc.code == 7

    assert calls == ["called"]
