"""Einzelbilder und kleine Bildfolgen aus dem Projekt (für Maskenrahmen und Tracking). Ohne Qt."""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..paths import find_binary
from . import exporter, window as projwin
from .project import Project

_NOWINDOW = 0x08000000 if os.name == "nt" else 0


def render_segment(project: Project, t: float, length: float, height: int, out_path: str,
                   should_cancel: Callable[[], bool] | None = None,
                   on_progress: Callable[[float], None] | None = None) -> float:
    """Rechnet [t, t+length] des Projekts ohne Effekte, Texte, Untertitel und Bild-in-Bild in kleiner Auflösung.

    Gibt die Länge des Ergebnisses zurück. Das Ergebnis zeigt nur das Bild der Clips (Format, Zuschnitt, Bewegung),
    so wie die Maske es später sieht – das reicht zum Platzieren und Verfolgen und ist schnell.
    """
    wp, delta, wl = projwin.project_window(project, t, max(0.5, length))
    wp.effects = []
    wp.texts = []
    wp.subtitles = []
    wp.overlays = []
    cmd, total, tmp = exporter.build_command(wp, out_path, draft=True, preview_height=height, start=delta, max_seconds=wl)
    try:
        exporter.run(cmd, total, on_progress, should_cancel)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return total


def extract_frame(video: str, png: str, t: float = 0.0) -> None:
    cmd = [find_binary("ffmpeg"), "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1", png]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=_NOWINDOW, timeout=60)
    if r.returncode != 0 or not Path(png).exists():
        raise RuntimeError(r.stderr.strip()[-300:] or "Einzelbild fehlgeschlagen")


def frame_at(project: Project, t: float, height: int, png: str, tmp_dir: str) -> None:
    """Ein Bild des Projekts bei t als PNG (ohne Effekte)."""
    mp4 = str(Path(tmp_dir) / "frame.mp4")
    render_segment(project, t, 0.5, height, mp4)
    try:
        extract_frame(mp4, png, 0.0)
    finally:
        try:
            os.remove(mp4)
        except OSError:
            pass


def read_gray(video: str, fps: float, width: int, height: int):
    """Alle Bilder als Graustufen-Feld (n, height, width), uint8. Braucht numpy."""
    import numpy as np
    cmd = [find_binary("ffmpeg"), "-v", "error", "-i", video, "-vf", f"fps={fps:g},scale={width}:{height},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=_NOWINDOW, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-300:] or "Bilder lesen fehlgeschlagen")
    data = np.frombuffer(r.stdout, dtype=np.uint8)
    n = data.size // (width * height)
    return data[: n * width * height].reshape(n, height, width)
