"""Presets laden. Mitgelieferte Presets + eigene/nachgeladene Presets des Benutzers.

Jede JSON-Datei in presets/ (oder %APPDATA%/ClipForge/presets) enthält Listen mit "id".
Presets des Benutzers überschreiben mitgelieferte mit gleicher id. So kann man später
neue Formate, Export-Einstellungen und Looks hinzufügen, ohne den Programmcode zu ändern.
"""
import json
from pathlib import Path

from ..paths import bundle_dir, user_presets_dir

KINDS = ("formats", "exports", "looks")


def _read(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def load(kind: str) -> list[dict]:
    """kind: 'formats' | 'exports' | 'looks'"""
    merged: dict[str, dict] = {}
    for folder in (bundle_dir() / "presets", user_presets_dir()):
        for item in _read(folder / f"{kind}.json"):
            if isinstance(item, dict) and "id" in item:
                merged[item["id"]] = item
    return list(merged.values())


def get(kind: str, preset_id: str) -> dict | None:
    for item in load(kind):
        if item["id"] == preset_id:
            return item
    return None
