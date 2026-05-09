from __future__ import annotations

from guildbridge.gui import GUI_THEMES


def test_desktop_gui_defines_light_and_dark_theme_palettes() -> None:
    required = {
        "bg",
        "surface",
        "surface_soft",
        "text",
        "muted",
        "border",
        "field",
        "field_focus",
        "select_bg",
        "select_fg",
        "button",
        "button_active",
        "output_bg",
        "output_fg",
    }

    assert set(GUI_THEMES) == {"Light", "Dark"}
    for palette in GUI_THEMES.values():
        assert required <= set(palette)
        assert all(value.startswith("#") for value in palette.values())
