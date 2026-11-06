"""Programm-Einstellungen (gelten für alle Projekte), gespeichert in %APPDATA%\\FATE VIDEOSCHNITT\\settings.json."""
from __future__ import annotations

import json

from .. import paths

DEFAULTS = {"preview_len": 8.0, "preview_height": 360, "hw_encode": False, "live_preview": True, "live_len": 6.0,
            # Oberfläche (1.4.2): wird beim Beenden gespeichert und beim Start wiederhergestellt
            "ui_locked": [], "ui_zoom": 1.0, "ui_hsplit": [], "ui_vsplit": [], "ui_tab": 0}


def clean_ui(raw: dict, n_lanes: int, n_tabs: int, max_zoom: float) -> dict:
    """Prüft gespeicherte Oberflächenwerte (kaputte oder veraltete Werte werden verworfen bzw. begrenzt)."""
    def sizes(v):
        if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0 for x in v) and sum(v) > 0:
            return [int(x) for x in v]
        return []
    lock = raw.get("ui_locked", [])
    lock = sorted({int(x) for x in lock if isinstance(x, int) and not isinstance(x, bool) and 0 <= x < n_lanes}) if isinstance(lock, list) else []
    z = raw.get("ui_zoom", 1.0)
    z = float(z) if isinstance(z, (int, float)) and not isinstance(z, bool) and z == z else 1.0
    tab = raw.get("ui_tab", 0)
    tab = tab if isinstance(tab, int) and not isinstance(tab, bool) and 0 <= tab < n_tabs else 0
    return {"ui_locked": lock, "ui_zoom": max(1.0, min(max_zoom, z)), "ui_hsplit": sizes(raw.get("ui_hsplit")),
            "ui_vsplit": sizes(raw.get("ui_vsplit")), "ui_tab": tab}


def _file():
    return paths.user_dir() / "settings.json"


def load() -> dict:
    d = dict(DEFAULTS)
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            d.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return d


def save(values: dict) -> None:
    d = load()
    d.update({k: v for k, v in values.items() if k in DEFAULTS})
    try:
        _file().write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        pass
