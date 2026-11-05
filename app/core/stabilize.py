"""Videostabilisierung mit FFmpeg (vidstab, zwei Durchgänge) und Rückfall auf `deshake`.

Durchgang 1 (Analyse) schreibt die Kamerabewegung einer Quellstrecke in eine .trf-Datei; sie wird zwischengespeichert.
Durchgang 2 (vidstabtransform) steht dann in der Filterkette des Clips. Für Ausschnitte (Live-Vorschau) wird aus einer
vorhandenen Analyse der passende Teil herausgeschnitten, statt neu zu rechnen. Das geht nur, wenn libvidstab die Datei als
Text schreibt (ältere Versionen). Neuere schreiben ein Binärformat („TRF1“); dann wird der Ausschnitt einzeln analysiert.

Hinweis Windows: libvidstab öffnet Dateien ohne UTF-8-Unterstützung. Darum liegen die .trf-Dateien in einem Ordner,
dessen Pfad nur aus ASCII-Zeichen besteht (sonst unter C:\\Users\\Public).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .. import paths
from ..paths import find_binary
from . import exporter
from .grade import esc_path

_NOWINDOW = 0x08000000 if os.name == "nt" else 0
MAX_ENTRIES = 40
SLACK = 0.05            # so viel Abweichung (Sekunden) gilt noch als „derselbe“ Bereich

_avail: bool | None = None


class StabilizeError(Exception):
    pass


# ---------------------------------------------------------------- Ablageort
def stab_dir() -> Path:
    base = paths.user_dir() / "stab"
    if os.name == "nt" and not str(base).isascii():
        pub = os.environ.get("PUBLIC")
        if pub and str(pub).isascii():
            base = Path(pub) / "FATE VIDEOSCHNITT" / "stab"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _index_file() -> Path:
    return stab_dir() / "index.json"


def _load_index() -> list[dict]:
    try:
        data = json.loads(_index_file().read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and Path(str(e.get("trf", ""))).exists()]
    except (OSError, ValueError):
        return []


def _save_index(items: list[dict]) -> None:
    while len(items) > MAX_ENTRIES:                       # älteste zuerst löschen
        old = items.pop(0)
        try:
            Path(old["trf"]).unlink()
        except OSError:
            pass
    try:
        _index_file().write_text(json.dumps(items), encoding="utf-8")
    except OSError:
        pass


def _sig(path: str) -> list:
    try:
        st = Path(path).stat()
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return [0, 0]


def available() -> bool:
    """Kennt dieses FFmpeg vidstabdetect und vidstabtransform?"""
    global _avail
    if _avail is None:
        try:
            r = subprocess.run([find_binary("ffmpeg"), "-hide_banner", "-filters"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", creationflags=_NOWINDOW, timeout=30)
            _avail = "vidstabdetect" in r.stdout and "vidstabtransform" in r.stdout
        except Exception:  # noqa: BLE001
            _avail = False
    return _avail


# ---------------------------------------------------------------- Analyse
def _name(path: str, a: float, b: float) -> str:
    return hashlib.sha1(f"{path}|{_sig(path)}|{a:.3f}|{b:.3f}".encode("utf-8")).hexdigest()[:20] + ".trf"


def analyze(path: str, in_pt: float, out_pt: float, should_cancel: Callable[[], bool] | None = None,
            on_progress: Callable[[float], None] | None = None) -> Path:
    """Durchgang 1 für [in_pt, out_pt] der Quelldatei; gibt den Pfad der .trf-Datei zurück (zwischengespeichert)."""
    hit = lookup(path, in_pt, out_pt)
    if hit is not None:
        return hit
    if not available():
        raise StabilizeError("Dieses FFmpeg hat keine Stabilisierung (vidstab).")
    span = max(0.05, out_pt - in_pt)
    trf = stab_dir() / _name(path, in_pt, out_pt)
    cmd = [find_binary("ffmpeg"), "-hide_banner", "-y", "-progress", "pipe:1", "-nostats",
           "-ss", f"{in_pt:.3f}", "-t", f"{span:.3f}", "-i", path,
           "-vf", f"vidstabdetect=shakiness=6:accuracy=9:result={esc_path(str(trf))}", "-f", "null", "-"]
    try:
        exporter.run(cmd, span, on_progress, should_cancel)
    except Exception:
        try:
            trf.unlink()
        except OSError:
            pass
        raise
    if not trf.exists() or trf.stat().st_size == 0:
        raise StabilizeError("Die Analyse hat keine Daten geliefert.")
    items = _load_index()
    items.append({"path": path, "sig": _sig(path), "in": round(in_pt, 3), "out": round(out_pt, 3), "trf": str(trf),
                  "frames": count_frames(trf)})
    _save_index(items)
    return trf


def count_frames(trf: Path | str) -> int:
    n = 0
    try:
        with open(trf, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("Frame "):
                    n += 1
    except OSError:
        return 0
    return n


def slice_trf(src: Path | str, dst: Path | str, first: int, count: int) -> None:
    """Schreibt die Bilder first … first+count−1 (ab 0) der Analyse neu nummeriert (ab 1) in `dst`."""
    head: list[str] = []
    body: list[str] = []
    with open(src, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"Frame (\d+) (\(.*)", line.rstrip("\n"))
            if not m:
                if not body:
                    head.append(line.rstrip("\n"))
                continue
            k = int(m.group(1)) - 1
            if first <= k < first + count:
                body.append(f"Frame {k - first + 1} {m.group(2)}")
    if not body:
        raise StabilizeError("Ausschnitt der Analyse ist leer.")
    Path(dst).write_text("\n".join(head + body) + "\n", encoding="utf-8")


def lookup(path: str, in_pt: float, out_pt: float) -> Path | None:
    """Analyse für genau diesen Bereich – oder ein passender Ausschnitt einer größeren. None = nichts vorhanden."""
    sig = _sig(path)
    best = None
    for e in _load_index():
        if e.get("path") != path or e.get("sig") != sig:
            continue
        a, b = float(e["in"]), float(e["out"])
        if abs(a - in_pt) <= SLACK and abs(b - out_pt) <= SLACK:
            return Path(e["trf"])
        if a - SLACK <= in_pt and out_pt <= b + SLACK and (best is None or (b - a) < (best[1] - best[0])):
            best = (a, b, e)
    if best is None:
        return None
    a, b, e = best
    out = stab_dir() / _name(path, in_pt, out_pt)
    if out.exists() and out.stat().st_size > 0:
        return out
    nf = int(e.get("frames") or count_frames(e["trf"]))
    if nf < 2 or b - a <= 0:
        return None
    fps = nf / (b - a)
    first = max(0, int(round((in_pt - a) * fps)))
    count = min(nf - first, max(2, int(round((out_pt - in_pt) * fps))))
    try:
        slice_trf(e["trf"], out, first, count)
    except (StabilizeError, OSError):
        return None
    return out


# ---------------------------------------------------------------- Filter
def strength_params(stab: int) -> tuple[int, float]:
    """(Glättung in Bildern, Zoom in %) für Stärke 1…100."""
    s = max(1, min(100, int(stab)))
    return int(round(4 + s * 0.46)), round(2.0 + s * 0.06, 2)


def filter_for(clip) -> str:
    """Filter-Text für den Clip (leer, wenn nicht stabilisiert). Ohne fertige Analyse → deshake als Notlösung."""
    stab = int(getattr(clip, "stabilize", 0) or 0)
    if stab <= 0 or getattr(clip, "is_image", False):
        return ""
    trf = lookup(clip.path, clip.in_pt, clip.out_pt) if available() else None
    if trf is not None:
        smooth, zoom = strength_params(stab)
        # optalgo=gauss: gleichmäßige Glättung wie bisher. Neuere libvidstab-Versionen nehmen sonst eine Pfad-Optimierung,
        # die ein Zoom-Budget braucht und mit festem Zoom viel zu schwach ausgleicht.
        return (f"vidstabtransform=input={esc_path(str(trf))}:smoothing={smooth}:optalgo=gauss:zoom={zoom}"
                ":optzoom=0:interpol=bicubic")
    rx = max(16, min(64, 16 * int(round((8 + stab * 0.32) / 16))))     # deshake: Suchbereich, nur Vielfache von 16 erlaubt
    return f"deshake=rx={rx}:ry={rx}:edge=mirror"


def missing(project) -> list:
    """Clips, die stabilisiert werden sollen, aber noch keine Analyse haben."""
    if not available():
        return []
    out = []
    for c in project.clips:
        if int(getattr(c, "stabilize", 0) or 0) > 0 and not c.is_image and lookup(c.path, c.in_pt, c.out_pt) is None:
            out.append(c)
    return out


def prepare(project, should_cancel: Callable[[], bool] | None = None,
            on_progress: Callable[[float], None] | None = None) -> int:
    """Analysiert alle fehlenden Clips nacheinander; gibt die Anzahl neu analysierter Clips zurück."""
    todo = missing(project)
    for k, c in enumerate(todo):
        analyze(c.path, c.in_pt, c.out_pt, should_cancel,
                (lambda p, k=k: on_progress((k + p) / len(todo))) if on_progress else None)
    return len(todo)
