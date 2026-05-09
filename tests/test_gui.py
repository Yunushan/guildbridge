from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_gui_exposes_apply_safety_controls() -> None:
    source = (ROOT / "src" / "guildbridge" / "gui.py").read_text(encoding="utf-8")

    assert "Journal output JSON" in source
    assert "Resume journal JSON" in source
    assert "Force invalid template after review" in source
    assert "simpledialog.askstring" in source
    assert "apply_confirmation_error" in source
    assert "Type APPLY to run provider writes using the reviewed plan." in source
    assert "assets/guildbridge-icon.png" in source
    assert "iconphoto" in source
    assert "iconbitmap" in source
    assert "DwmSetWindowAttribute" in source
    assert "GetAncestor" in source
    assert "_refresh_windows_titlebar" in source
    assert "_apply_windows_titlebar" in source
