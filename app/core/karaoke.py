"""Karaoke-Untertitel: Wortzeiten und Zeilenaufbau.

Die Wortzeiten werden aus der Länge der Wörter über die Dauer des Eintrags verteilt (funktioniert auch
für importierte SRT-Dateien und von Hand getippte Einträge). Der Zeilenaufbau legt jedes Wort auf eine
feste Pixelposition, damit Grundfarbe und Hervorhebung exakt aufeinander liegen.
"""
from __future__ import annotations

import textwrap
from typing import Callable

MAX_WORDS = 60             # längere Einträge werden normal (ohne Karaoke) gezeigt
MODES = {"stay": "Gesprochene Wörter bleiben hervorgehoben", "active": "Nur das gerade gesprochene Wort leuchtet"}
DEFAULT_COLOR = "#ffd400"


def word_times(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    """[(Wort, Beginn, Ende)] – die Dauer wird nach Wortlänge (mit Mindestgewicht) verteilt."""
    words = text.split()
    if not words:
        return []
    dur = max(0.05, float(end) - float(start))
    weights = [max(2.0, len(w) + 1.0) for w in words]
    total = sum(weights)
    out, t = [], float(start)
    for w, wt in zip(words, weights):
        d = dur * wt / total
        out.append((w, t, t + d))
        t += d
    out[-1] = (out[-1][0], out[-1][1], float(end))
    return out


def layout(text: str, measure: Callable[[str], float], W: int, max_chars: int) -> list[list[tuple[str, float]]] | None:
    """Zeilen mit (Wort, x links in Pixeln); jede Zeile mittig im Bild. None, wenn das Umbrechen die Wörter verändert."""
    lines = [textwrap.fill(line, max_chars) for line in (text.splitlines() or [""])]
    wrapped = "\n".join(lines)
    if wrapped.split() != text.split():
        return None
    space = measure(" ")
    out: list[list[tuple[str, float]]] = []
    for line in wrapped.split("\n"):
        ws = line.split()
        if not ws:
            continue
        widths = [measure(w) for w in ws]
        total = sum(widths) + space * (len(ws) - 1)
        x = max(0.0, (W - total) / 2.0)
        row = []
        for w, wd in zip(ws, widths):
            row.append((w, x))
            x += wd + space
        out.append(row)
    return out
