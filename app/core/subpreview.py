"""Vorschaubild der Untertitel: ein Standbild des Projekts an einer Stelle mit Untertitel (wie im Export). Ohne Qt."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from . import exporter, frames
from .project import Project


def pick_time(project: Project, playhead: float = -1.0, selected: int = -1) -> float | None:
    """Zeitpunkt für die Vorschau: Mitte des gewählten Eintrags, sonst der Abspielkopf (wenn dort ein Eintrag läuft),
    sonst die Mitte des ersten Eintrags. None, wenn es keine Untertitel gibt."""
    cues = [c for c in project.subtitles if c.text.strip()]
    if not cues:
        return None
    subs = project.subtitles
    if 0 <= selected < len(subs) and subs[selected].text.strip():
        c = subs[selected]
        return (c.start + c.end) / 2.0
    if playhead >= 0 and any(c.start <= playhead <= c.end for c in cues):
        return float(playhead)
    c = min(cues, key=lambda c: c.start)
    return (c.start + c.end) / 2.0


def render(project: Project, t: float, png_path: str, height: int = 480) -> None:
    """Rechnet ein Bild des Projekts zur Zeit t (Sekunden)."""
    if not project.clips:
        raise RuntimeError("Das Projekt enthält keine Clips.")
    tmp = Path(tempfile.mkdtemp(prefix="fate_subprev_"))
    try:
        out = str(tmp / "s.mp4")
        t = max(0.0, min(float(t), max(0.0, project.duration - 0.5)))
        cmd, total, work = exporter.build_command(project, out, draft=True, start=t, max_seconds=0.5,
                                                  preview_height=height)
        try:
            exporter.run(cmd, total)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        frames.extract_frame(out, png_path, 0.05)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not Path(png_path).is_file():
        raise RuntimeError("Das Vorschaubild konnte nicht erstellt werden.")
