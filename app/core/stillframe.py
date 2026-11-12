"""Aktuelles Bild als PNG speichern: genau das Bild, das der Export an dieser Stelle zeigt (Effekte, Text, Logo, Untertitel)."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from .. import paths
from . import exporter
from .project import Project


def clamp_time(project: Project, t: float) -> float:
    """Die Zeit liegt im Projekt; das allerletzte Bild ist erst ein kleines Stück vor dem Ende sicher vorhanden."""
    return max(0.0, min(float(t), max(0.0, project.duration - 0.1)))


def default_name(project: Project, t: float) -> str:
    sec = int(clamp_time(project, t))
    return f"Standbild_{sec // 60:02d}-{sec % 60:02d}.png"


def build(project: Project, t: float, out_png: str):
    """Gibt (Kommando fürs Zwischenvideo, Dauer, temp-Ordner, Kommando fürs PNG) zurück. Das Projekt selbst bleibt unverändert."""
    if not project.clips:
        raise exporter.ExportError("Das Projekt enthält keine Clips.")
    t = clamp_time(project, t)
    p = copy.deepcopy(project)
    p.export_id = "fast_draft"                          # nur ein Zwischenschritt: schnell kodieren
    tmp_dir = Path(tempfile.mkdtemp(prefix="fate_still_"))
    mid = str(tmp_dir / "still.mp4")
    cmd, total, tmp = exporter.build_command(p, mid, start=t, max_seconds=0.5)
    png_cmd = [paths.find_binary("ffmpeg"), "-hide_banner", "-y", "-i", mid, "-frames:v", "1", out_png]
    return cmd, total, tmp, png_cmd


def render(project: Project, t: float, out_png: str) -> None:
    """Rechnet und speichert das Bild (für Tests und Skripte; die Oberfläche nutzt build() mit Fortschrittsanzeige)."""
    import subprocess
    cmd, total, _tmp, png_cmd = build(project, t, out_png)
    exporter.run(cmd, total)
    r = subprocess.run(png_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not Path(out_png).is_file():
        raise exporter.ExportError("Das Bild konnte nicht gespeichert werden:\n" + r.stderr[-400:])
