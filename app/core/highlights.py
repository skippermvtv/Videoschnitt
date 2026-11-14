"""Highlights finden: die besten Abschnitte (z. B. für Shorts) vorschlagen. Ohne Qt.

Eine Heuristik, keine Bildverständnis-KI. Bewertet wird jedes Zeitfenster der gewünschten Länge nach
  • Lautstärke (laute Stellen: Lachen, Aufregung, Musikhöhepunkte, Treffer im Spiel),
  • Sprechdichte (Wörter pro Sekunde laut Untertiteln mit Wortzeiten, falls vorhanden),
  • Schnittdichte (viele Clipwechsel = viel Bewegung).
Die besten, sich nicht überlappenden Fenster werden als Marker gesetzt. Ob die Auswahl zu deinen Videos passt, prüfst du selbst.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

import numpy as np

from ..paths import find_binary
from .project import Project

_NOWINDOW = 0x08000000 if os.name == "nt" else 0
SR = 8000                     # Abtastrate der Analyse
BIN = 1.0                     # Sekunden je Messwert
SILENT_DB = -90.0
MIN_WINDOW, MAX_WINDOW = 5.0, 180.0
W_LOUD, W_PEAK, W_SPEECH, W_CUTS = 0.45, 0.20, 0.20, 0.15


class HighlightError(Exception):
    pass


@dataclass
class Highlight:
    start: float
    end: float
    score: float                                            # 0…1 (relativ zu den anderen Fenstern dieses Projekts)
    reasons: list[str] = field(default_factory=list)       # z. B. „laut“, „viel gesprochen“, „viele Schnitte“

    @property
    def length(self) -> float:
        return self.end - self.start


def loudness_bins(project: Project, timeout: float = 300.0) -> np.ndarray:
    """Pegel (dBFS, RMS) je Sekunde der Timeline aus dem Ton der Clips; Stellen ohne Ton = SILENT_DB."""
    total = project.duration
    n = max(1, int(np.ceil(total / BIN)))
    out = np.full(n, SILENT_DB, dtype=np.float64)
    starts = project.clip_starts()
    for i, c in enumerate(project.clips):
        if c.is_image or not c.has_audio or c.mute or c.audio_detached:
            continue
        span = max(0.0, c.out_pt - c.in_pt)
        if span < 0.2:
            continue
        cmd = [find_binary("ffmpeg"), "-v", "error", "-ss", f"{c.in_pt:.3f}", "-t", f"{span:.3f}", "-i", c.path,
               "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, creationflags=_NOWINDOW, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            continue
        x = np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)
        if len(x) < SR // 4:
            continue
        sp = max(0.01, c.speed)
        step = max(1, int(round(SR * BIN * sp)))                 # Quell-Abtastwerte je Timeline-Sekunde
        usable = len(x) // step * step
        if usable == 0:
            continue
        blocks = x[:usable].reshape(-1, step)
        db = 10.0 * np.log10(np.mean(blocks * blocks, axis=1) + 1e-12)
        first = int(round(starts[i] / BIN))
        for k, v in enumerate(db):
            if 0 <= first + k < n:
                out[first + k] = max(out[first + k], v)
    return np.maximum(out, SILENT_DB)


def speech_bins(project: Project, n: int) -> np.ndarray:
    """Wörter je Sekunde (aus den Wortzeiten der Untertitel); ohne Wortzeiten nach Textlänge verteilt."""
    out = np.zeros(n)
    for cue in project.subtitles:
        if cue.words:
            for w in cue.words:
                try:
                    k = int((cue.start + (float(w[1]) + float(w[2])) / 2) / BIN)
                except (TypeError, ValueError, IndexError):
                    continue
                if 0 <= k < n:
                    out[k] += 1.0
        else:
            words = cue.text.split()
            if not words or cue.end <= cue.start:
                continue
            a, b = int(cue.start / BIN), int(max(cue.start / BIN, (cue.end - 1e-6) / BIN))
            for k in range(a, min(b, n - 1) + 1):
                out[k] += len(words) / max(1, b - a + 1)
    return out


def cut_bins(project: Project, n: int) -> np.ndarray:
    """Clipwechsel je Sekunde."""
    out = np.zeros(n)
    for s in project.clip_starts()[1:]:
        k = int(s / BIN)
        if 0 <= k < n:
            out[k] += 1.0
    return out


def _rank01(x: np.ndarray) -> np.ndarray:
    """Rang jedes Werts 0…1 (gleiche Werte bekommen denselben mittleren Rang) – macht verschieden skalierte Messwerte vergleichbar."""
    if len(x) == 0:
        return x
    _u, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    end = np.cumsum(cnt)
    avg = (end - cnt + end - 1) / 2.0
    return avg[inv] / max(1, len(x) - 1)


def score_windows(loud_db: np.ndarray, speech: np.ndarray, cuts: np.ndarray, window: float) -> tuple[np.ndarray, list[list[str]]]:
    """Wert je Fensteranfang (Schritt = BIN) und die Gründe. Länge des Ergebnisses: n − Fenster + 1."""
    n = len(loud_db)
    w = max(1, int(round(window / BIN)))
    if n < w:
        raise HighlightError("Das Projekt ist kürzer als das gewünschte Fenster.")
    m = n - w + 1
    csum = lambda a: np.concatenate([[0.0], np.cumsum(a)])      # noqa: E731
    energy = 10 ** (loud_db / 10.0)
    ce, cs, cc = csum(energy), csum(speech), csum(cuts)
    mean_e = (ce[w:] - ce[:-w]) / w
    mean_db = np.round(10.0 * np.log10(mean_e + 1e-12), 2)           # Rundung gegen Rechenrauschen der Summen (sonst kein Gleichstand)
    peak = np.array([loud_db[i:i + w].max() for i in range(m)])
    sp = np.round((cs[w:] - cs[:-w]) / w, 6)
    cu = np.round((cc[w:] - cc[:-w]) / w, 6)
    parts = {"laut": _rank01(mean_db), "Lautstärkespitze": _rank01(peak), "viel gesprochen": _rank01(sp) if sp.max() > 0 else np.zeros(m),
             "viele Schnitte": _rank01(cu) if cu.max() > 0 else np.zeros(m)}
    weights = {"laut": W_LOUD, "Lautstärkespitze": W_PEAK, "viel gesprochen": W_SPEECH, "viele Schnitte": W_CUTS}
    used = {k: weights[k] for k in parts if k in ("laut", "Lautstärkespitze") or parts[k].max() > 0}
    tot = sum(used.values())
    score = sum(parts[k] * used[k] for k in used) / tot
    reasons = [[k for k in used if parts[k][i] >= 0.8] for i in range(m)]
    return score, reasons


def pick(score: np.ndarray, reasons: list[list[str]], window: float, count: int, total: float) -> list[Highlight]:
    """Die `count` besten Fenster, die sich nicht überlappen."""
    w = max(1, int(round(window / BIN)))
    taken = np.zeros(len(score) + w, dtype=bool)
    out: list[Highlight] = []
    for i in np.argsort(-score, kind="stable"):
        i = int(i)
        if len(out) >= count:
            break
        if taken[max(0, i - w + 1):i + w].any():
            continue
        taken[i:i + w] = True
        out.append(Highlight(i * BIN, min(total, i * BIN + window), float(score[i]), reasons[i]))
    out.sort(key=lambda h: h.start)
    return out


def find(project: Project, window: float = 30.0, count: int = 5) -> list[Highlight]:
    window = max(MIN_WINDOW, min(MAX_WINDOW, float(window)))
    count = max(1, min(20, int(count)))
    if not project.clips:
        raise HighlightError("Das Projekt ist leer.")
    total = project.duration
    if total < window + BIN:
        raise HighlightError(f"Das Projekt ({total:.0f} s) ist zu kurz für Abschnitte von {window:.0f} s.")
    loud = loudness_bins(project)
    n = len(loud)
    if not (loud > SILENT_DB + 1).any() and not project.subtitles:
        raise HighlightError("Im Projekt gibt es keinen Ton und keine Untertitel, nach denen sich etwas bewerten ließe.")
    score, reasons = score_windows(loud, speech_bins(project, n), cut_bins(project, n), window)
    return pick(score, reasons, window, count, total)


def describe(h: Highlight, number: int) -> str:
    def t(x: float) -> str:
        m, s = divmod(int(round(x)), 60)
        return f"{m}:{s:02d}"
    why = f" – {', '.join(h.reasons)}" if h.reasons else ""
    return f"Highlight {number}: {t(h.start)}–{t(h.end)} ({h.length:.0f} s){why}"


def apply_markers(project: Project, found: list[Highlight]) -> int:
    """Setzt je Highlight einen Marker am Anfang („★ Highlight 1“) und am Ende („★ Ende 1“); gibt die Zahl neuer Marker zurück."""
    from . import markers
    before = len(project.markers)
    for k, h in enumerate(found, 1):
        markers.add(project, h.start, f"★ Highlight {k}")
        markers.add(project, h.end, f"★ Ende {k}")
    return len(project.markers) - before
