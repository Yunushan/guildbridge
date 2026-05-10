from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_gui_exposes_apply_safety_controls() -> None:
    source = (ROOT / "src" / "guildbridge" / "gui.py").read_text(encoding="utf-8")

    assert "Journal output JSON" in source
    assert "Resume journal JSON" in source
    assert "Force invalid template after review" in source
    assert "Dry-run Check" in source
    assert "Actual Run" in source
    assert "_run_dry_run" in source
    assert "Dry-run Check requires a Plan/result JSON file path" in source
    assert "messagebox.askyesno" in source
    assert "_reviewed_plan_preview" in source
    assert "apply_confirmation_error" in source
    assert "assets/guildbridge-icon.png" in source
    assert "iconphoto" in source
    assert "iconbitmap" in source
    assert "DwmSetWindowAttribute" in source
    assert "GetAncestor" in source
    assert "_refresh_windows_titlebar" in source
    assert "_apply_windows_titlebar" in source
    assert "_result_dialog_message" in source
    assert "Actual run requires Plan/result JSON to be empty" in (
        ROOT / "src" / "guildbridge" / "gui_commands.py"
    ).read_text(encoding="utf-8")
