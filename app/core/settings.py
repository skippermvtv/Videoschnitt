"""Programm-Einstellungen (gelten für alle Projekte), gespeichert in %APPDATA%\\FATE VIDEOSCHNITT\\settings.json."""
from __future__ import annotations

import json

from .. import paths

DEFAULTS = {"preview_len": 8.0, "preview_height": 360, "hw_encode": False}


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
