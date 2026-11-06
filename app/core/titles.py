"""Titel-Vorlagen (presets/titles.json) in Textebenen umsetzen. Ohne Qt."""
from __future__ import annotations

from . import presets
from .project import TEXT_ANIMS, TextLayer

POSITIONS = ("top", "center", "bottom")


def templates() -> list[dict]:
    return [t for t in presets.load("titles") if isinstance(t, dict) and t.get("id") and t.get("name")]


def make_layer(tpl: dict, start: float, fonts: dict[str, str] | None = None, default_font: str = "") -> TextLayer:
    """Textebene aus einer Vorlage. `fonts` ordnet Schriftnamen (Dateiname ohne Endung) ihrem Pfad zu."""
    fonts = fonts or {}
    anims = {a for a, _ in TEXT_ANIMS}
    try:
        dur = min(60.0, max(0.5, float(tpl.get("duration", 4.0))))
    except (TypeError, ValueError):
        dur = 4.0
    try:
        size = min(40.0, max(1.0, float(tpl.get("size_pct", 7.0))))
    except (TypeError, ValueError):
        size = 7.0
    try:
        adur = min(5.0, max(0.05, float(tpl.get("anim_dur", 0.4))))
    except (TypeError, ValueError):
        adur = 0.4
    font = fonts.get(str(tpl.get("font_stem", "")), "") or default_font
    start = max(0.0, float(start))
    return TextLayer(text=str(tpl.get("text", "Dein Text")), start=start, end=start + dur,
                     position=tpl.get("position") if tpl.get("position") in POSITIONS else "center",
                     size_pct=size, color=str(tpl.get("color", "#ffffff")), border_color=str(tpl.get("border_color", "#000000")),
                     font=font, anim=tpl.get("anim") if tpl.get("anim") in anims else "none", anim_dur=adur,
                     box=bool(tpl.get("box", False)))
