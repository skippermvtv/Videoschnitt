"""Stille automatisch aus einem Clip schneiden (Jump-Cut): Pausen finden (FFmpeg silencedetect), Schnitte berechnen,
den Clip in die verbleibenden Stücke teilen. Ohne Qt."""
from __future__ import annotations

import re
import subprocess

from ..paths import find_binary
from . import pieces
from .pieces import PieceError as SilenceError
from .project import Clip, Project

_NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")

DEFAULT_DB = -35.0        # Leiser als dies gilt als Stille
DEFAULT_MIN = 0.5         # Mindestlänge einer Pause in Sekunden
DEFAULT_PAD = 0.12        # so viel Pause bleibt vor und nach dem Gesprochenen stehen
MIN_CUT = 0.10            # kürzere Schnitte lohnen sich nicht
MIN_PIECE = 0.08          # kürzere verbleibende Stücke werden weggelassen


def parse(stderr: str, length: float) -> list[tuple[float, float]]:
    """Pausen (Beginn, Ende) in Sekunden ab Anfang der Analyse aus der FFmpeg-Ausgabe. Eine Pause ohne Ende reicht bis `length`."""
    out: list[tuple[float, float]] = []
    start: float | None = None
    for line in (stderr or "").splitlines():
        m = _START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _END.search(line)
        if m and start is not None:
            out.append((start, min(length, float(m.group(1)))))
            start = None
    if start is not None and start < length:
        out.append((start, length))
    return [(a, b) for a, b in out if b > a]


def detect(clip: Clip, noise_db: float = DEFAULT_DB, min_dur: float = DEFAULT_MIN, timeout: float = 600.0) -> list[tuple[float, float]]:
    """Pausen im Ausschnitt des Clips; Zeiten in Quell-Sekunden (wie in_pt/out_pt)."""
    if clip.is_image or not clip.has_audio:
        raise SilenceError("Dieser Clip hat keinen Ton.")
    length = max(0.0, clip.out_pt - clip.in_pt)
    if length < 0.2:
        raise SilenceError("Der Clip ist zu kurz.")
    cmd = [find_binary("ffmpeg"), "-hide_banner", "-nostats", "-ss", f"{clip.in_pt:.3f}", "-t", f"{length:.3f}", "-i", clip.path,
           "-vn", "-af", f"silencedetect=noise={noise_db:.1f}dB:d={max(0.05, min_dur):.3f}", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=_NOWINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SilenceError(f"Die Analyse konnte nicht gestartet werden: {exc}") from exc
    if r.returncode != 0:
        raise SilenceError("Die Analyse des Tons ist fehlgeschlagen.")
    return [(clip.in_pt + a, clip.in_pt + b) for a, b in parse(r.stderr, length)]


def cuts_from(silences: list[tuple[float, float]], in_pt: float, out_pt: float, pad: float = DEFAULT_PAD) -> list[tuple[float, float]]:
    """Schnitte: jede Pause wird um `pad` an beiden Seiten verkleinert; zu kurze Schnitte entfallen."""
    out = []
    for a, b in sorted(silences):
        a, b = max(in_pt, a + pad), min(out_pt, b - pad)
        if b - a >= MIN_CUT:
            if out and a <= out[-1][1] + 1e-6:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
    return out


def keeps(cuts: list[tuple[float, float]], in_pt: float, out_pt: float) -> list[tuple[float, float]]:
    """Die verbleibenden Stücke (Quell-Sekunden) zwischen den Schnitten."""
    res, pos = [], in_pt
    for a, b in cuts:
        if a - pos >= MIN_PIECE:
            res.append((pos, a))
        pos = max(pos, b)
    if out_pt - pos >= MIN_PIECE:
        res.append((pos, out_pt))
    return res


def summary(cuts: list[tuple[float, float]], in_pt: float, out_pt: float, speed: float = 1.0) -> dict:
    """Zahlen für die Vorschau: Anzahl Pausen, entfernte Sekunden (auf der Timeline), Länge vorher/nachher."""
    removed = sum(b - a for a, b in cuts) / max(speed, 0.01)
    total = (out_pt - in_pt) / max(speed, 0.01)
    return {"cuts": len(cuts), "removed": removed, "before": total, "after": max(0.0, total - removed),
            "pieces": len(keeps(cuts, in_pt, out_pt))}


def describe(s: dict) -> str:
    def t(x: float) -> str:
        m, sec = divmod(int(round(x)), 60)
        return f"{m}:{sec:02d}"
    if not s["cuts"]:
        return "Keine Pausen gefunden. Mit einer höheren Schwelle (näher an 0 dB) oder kürzerer Mindestlänge erneut versuchen."
    return f"{s['cuts']} Pausen, {s['removed']:.1f} s entfallen (von {t(s['before'])} auf {t(s['after'])})."


def apply(project: Project, idx: int, cuts: list[tuple[float, float]]) -> list[int]:
    """Teilt den Clip `idx` in die Stücke zwischen den Schnitten; gibt die Indizes der neuen Stücke zurück."""
    if not 0 <= idx < len(project.clips):
        raise SilenceError("Kein Clip gewählt.")
    c = project.clips[idx]
    ks = keeps(cuts, c.in_pt, c.out_pt)
    if not ks:
        raise SilenceError("Es bliebe nichts übrig. Die Schwelle ist zu hoch gewählt.")
    return pieces.split_into(project, idx, ks)
