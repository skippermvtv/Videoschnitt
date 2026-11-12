"""Szenenerkennung: Stellen finden, an denen sich das Bild stark ändert, und den Clip dort teilen. Ohne Qt."""
from __future__ import annotations

import re
import subprocess

from ..paths import find_binary
from . import pieces
from .pieces import PieceError as SceneError
from .project import Clip, Project

_NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PTS = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")

DEFAULT_THRESHOLD = 0.30      # 0…1: höher = nur sehr deutliche Schnitte
DEFAULT_MIN_LEN = 0.5         # kürzere Szenen werden nicht gebildet


def parse(stderr: str) -> list[float]:
    """Zeiten (Sekunden ab Anfang der Analyse) aus den showinfo-Zeilen von FFmpeg."""
    out = []
    for line in (stderr or "").splitlines():
        if "showinfo" in line:
            m = _PTS.search(line)
            if m:
                out.append(max(0.0, float(m.group(1))))
    return sorted(set(out))


def detect(clip: Clip, threshold: float = DEFAULT_THRESHOLD, timeout: float = 900.0) -> list[float]:
    """Szenenwechsel im Ausschnitt des Clips; Zeiten in Quell-Sekunden (wie in_pt/out_pt)."""
    if clip.is_image:
        raise SceneError("Bei einem Standbild geht das nicht.")
    length = max(0.0, clip.out_pt - clip.in_pt)
    if length < 0.5:
        raise SceneError("Der Clip ist zu kurz.")
    t = max(0.01, min(0.99, float(threshold)))
    cmd = [find_binary("ffmpeg"), "-hide_banner", "-nostats", "-ss", f"{clip.in_pt:.3f}", "-t", f"{length:.3f}", "-i", clip.path,
           "-an", "-vf", f"scale=320:-2,select='gt(scene,{t:.3f})',showinfo", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=_NOWINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SceneError(f"Die Analyse konnte nicht gestartet werden: {exc}") from exc
    if r.returncode != 0:
        raise SceneError("Die Analyse des Bildes ist fehlgeschlagen.")
    return [clip.in_pt + x for x in parse(r.stderr) if x < length]


def cuts_from(times: list[float], in_pt: float, out_pt: float, min_len: float = DEFAULT_MIN_LEN) -> list[float]:
    """Schnittstellen: nicht zu nah am Anfang, am Ende oder aneinander."""
    out: list[float] = []
    last = in_pt
    for t in sorted(times):
        if t - last >= min_len and out_pt - t >= min_len:
            out.append(t)
            last = t
    return out


def ranges(cuts: list[float], in_pt: float, out_pt: float) -> list[tuple[float, float]]:
    edges = [in_pt, *cuts, out_pt]
    return list(zip(edges[:-1], edges[1:]))


def describe(cuts: list[float], in_pt: float, out_pt: float) -> str:
    if not cuts:
        return "Keine Szenenwechsel gefunden. Mit einer niedrigeren Empfindlichkeitsschwelle erneut versuchen."
    lens = [b - a for a, b in ranges(cuts, in_pt, out_pt)]
    return f"{len(cuts)} Schnitte, es entstehen {len(cuts) + 1} Szenen (kürzeste {min(lens):.1f} s, längste {max(lens):.1f} s)."


def apply(project: Project, idx: int, cuts: list[float]) -> list[int]:
    """Teilt den Clip `idx` an den Schnittstellen; gibt die Indizes der neuen Stücke zurück."""
    if not 0 <= idx < len(project.clips):
        raise SceneError("Kein Clip gewählt.")
    c = project.clips[idx]
    inner = cuts_from(cuts, c.in_pt, c.out_pt, 0.05)
    if not inner:
        raise SceneError("Es gibt keine Schnittstellen.")
    return pieces.split_into(project, idx, ranges(inner, c.in_pt, c.out_pt))
