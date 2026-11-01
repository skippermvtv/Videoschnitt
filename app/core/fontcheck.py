"""Prüft, ob eine Schriftdatei alle Zeichen eines Textes enthält (fehlende Zeichen bleiben im Video leer)."""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=16)
def _codepoints(path: str) -> frozenset[int]:
    from fontTools.ttLib import TTFont  # lazy: nur wenn gebraucht
    font = TTFont(path, lazy=True, fontNumber=0)
    try:
        return frozenset(font.getBestCmap().keys())
    finally:
        font.close()


def missing_chars(font_path: str, text: str) -> str:
    """Gibt die Zeichen aus text zurück, die font_path nicht enthält (ohne Doppelte, ohne Leerraum)."""
    if not font_path:
        return ""
    try:
        have = _codepoints(font_path)
    except Exception:  # noqa: BLE001 - Schrift nicht lesbar / fontTools fehlt → keine Warnung
        return ""
    out: list[str] = []
    for ch in text:
        if ch.isspace() or ord(ch) in have or ch in out:
            continue
        out.append(ch)
    return "".join(out)
