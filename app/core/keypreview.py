"""Vorschaubild für den Chroma-Key eines Clips: ein Standbild mit Key über dem Hintergrund (wie im Export). Ohne Qt."""
from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path

from . import exporter, frames
from .project import Clip, Project


def render(clip: Clip, png_path: str, height: int = 360, at: float | None = None) -> None:
    """Rechnet ein Bild des Clips mit Key und Hintergrund. at = Sekunden in der Quelle (Standard: Mitte des Clips)."""
    c = copy.deepcopy(clip)
    c.speed, c.reverse, c.transition, c.transition_dur = 1.0, False, "", 0.0
    c.ramp_id, c.ramp_pts, c.ramp_keys = "", [], []
    c.keyframes = []
    if not c.is_image:
        span = max(0.1, c.out_pt - c.in_pt)
        t = c.in_pt + (span / 2.0 if at is None else max(0.0, min(at, span)))
        c.in_pt = min(max(0.0, t), max(0.0, c.out_pt - 0.1))
        c.out_pt = min(c.duration, c.in_pt + 0.5)
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [c]
    tmp = Path(tempfile.mkdtemp(prefix="fate_keyprev_"))
    try:
        out = str(tmp / "k.mp4")
        cmd, total, work = exporter.build_command(p, out, draft=True, preview_height=height, max_seconds=0.5)
        try:
            exporter.run(cmd, total)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        frames.extract_frame(out, png_path, 0.1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not Path(png_path).is_file():
        raise RuntimeError("Das Vorschaubild konnte nicht erstellt werden.")
