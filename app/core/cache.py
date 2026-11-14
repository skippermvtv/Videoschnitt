"""Zwischenspeicher-Verwaltung: Größe anzeigen, begrenzen und leeren.

Nur Dateien, die sich jederzeit neu berechnen lassen, gelten als Zwischenspeicher: Proxys, Vorschau-Videos, Wellenformen,
Vorschaubilder und Stabilisierungs-Analysen. Standbilder (Projekte brauchen sie), Spracherkennung, eigene Schriften und
Vorlagen gehören nicht dazu und werden nie angefasst.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from .. import paths

DEFAULT_PROXY_LIMIT_GB = 20.0


@dataclass
class Location:
    key: str
    label: str
    note: str
    path: Path
    patterns: tuple[str, ...] = ("*",)


def locations() -> list[Location]:
    from . import preview, proxy, stabilize, waveform
    return [
        Location("proxies", "Proxys (kleine Vorschau-Kopien)", "Werden bei Bedarf neu erstellt.", proxy.proxy_dir(), ("*.mp4",)),
        Location("preview", "Vorschau-Videos", "Zwischenergebnisse der Live-Vorschau.", preview.cache_dir(), ("*.mp4",)),
        Location("stab", "Stabilisierungs-Analysen", "Werden beim nächsten Stabilisieren neu berechnet.", stabilize.stab_dir(), ("*.trf", "index.json")),
        Location("wave", "Wellenformen", "Bilder der Tonspuren.", waveform.cache_dir(), ("*.png",)),
        Location("thumbs", "Vorschaubilder der Medienliste", "Kleine Bilder der importierten Dateien.", paths.user_dir() / "thumbs", ("*.png",)),
    ]


def _files(loc: Location) -> list[Path]:
    out: list[Path] = []
    try:
        if not loc.path.is_dir():
            return out
        for pat in loc.patterns:
            out.extend(f for f in loc.path.glob(pat) if f.is_file())
    except OSError:
        pass
    return out


def _size(f: Path) -> int:
    try:
        return f.stat().st_size
    except OSError:
        return 0


def overview() -> list[dict]:
    """[{key, label, note, files, bytes, path}] für jede Stelle."""
    rows = []
    for loc in locations():
        fs = _files(loc)
        rows.append({"key": loc.key, "label": loc.label, "note": loc.note, "files": len(fs),
                     "bytes": sum(_size(f) for f in fs), "path": str(loc.path)})
    return rows


def human(n: float) -> str:
    for unit in ("Bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} {unit}" if unit == "Bytes" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return f"{n:.1f} GB"


def clear(keys) -> int:
    """Leert die gewählten Stellen; gibt die freigegebenen Bytes zurück. Dateien, die gerade benutzt werden, bleiben (Fehler werden übergangen)."""
    want = set(keys)
    freed = 0
    for loc in locations():
        if loc.key not in want:
            continue
        for f in _files(loc):
            n = _size(f)
            try:
                f.unlink()
                freed += n
            except OSError:
                pass
    return freed


def enforce_limit(key: str, max_bytes: int) -> int:
    """Hält eine Stelle unter max_bytes: die am längsten ungenutzten Dateien (älteste Änderungszeit) werden zuerst gelöscht.
    Gibt die gelöschten Bytes zurück. Angefangene Dateien (*.part*) werden übergangen."""
    loc = next((x for x in locations() if x.key == key), None)
    if loc is None or max_bytes < 0:
        return 0
    fs = [f for f in _files(loc) if ".part" not in f.name]
    total = sum(_size(f) for f in fs)
    freed = 0
    for f in sorted(fs, key=lambda p: p.stat().st_mtime if p.exists() else 0):
        if total - freed <= max_bytes:
            break
        n = _size(f)
        try:
            f.unlink()
            freed += n
        except OSError:
            pass
    return freed


def touch(path: str) -> None:
    """Merkt sich die Benutzung (für die Reihenfolge beim Aufräumen)."""
    try:
        os.utime(path, (time.time(), time.time()))
    except OSError:
        pass
