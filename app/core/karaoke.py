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


GAP_FILL = 0.4            # kleinere Pausen zwischen zwei Wörtern überbrückt „nur das gesprochene Wort“, damit nichts flackert


def valid_words(text: str, words, dur: float) -> list[tuple[str, float, float]] | None:
    """Prüft echte Wortzeiten ([[Wort, Beginn, Ende], …] ab Start des Eintrags): gleiche Wörter wie im Text, vernünftige Zeiten.
    Gibt die bereinigte Liste zurück oder None (dann wird nach Wortlänge verteilt, z. B. weil der Text bearbeitet wurde)."""
    toks = text.split()
    if not toks or not isinstance(words, (list, tuple)) or len(words) != len(toks):
        return None
    out: list[tuple[str, float, float]] = []
    last = 0.0
    for tok, w in zip(toks, words):
        try:
            wt, s, e = str(w[0]).strip(), float(w[1]), float(w[2])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        if wt != tok or s != s or e != e or s < -0.001 or e < s - 0.001 or s < last - 0.25 or s > dur + 0.5:
            return None
        s = max(s, last)
        e = max(e, s)
        out.append((tok, s, e))
        last = s
    return out


def word_times(text: str, start: float, end: float, words=None) -> list[tuple[str, float, float]]:
    """[(Wort, Beginn, Ende)] – mit echten Wortzeiten (`words`, relativ zum Start), sonst nach Wortlänge über die Dauer verteilt."""
    real = valid_words(text, words, max(0.05, float(end) - float(start))) if words else None
    if real:
        out = []
        for i, (w, s, e) in enumerate(real):
            t0 = min(float(end), float(start) + s)
            t1 = min(float(end), float(start) + e)
            if i + 1 < len(real):
                nxt = min(float(end), float(start) + real[i + 1][1])
                if 0.0 <= nxt - t1 <= GAP_FILL:
                    t1 = nxt
            out.append((w, t0, max(t0, t1)))
        return out
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
