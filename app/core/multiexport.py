"""Mehrere Formate in einem Rutsch exportieren (z. B. YouTube 16:9, Shorts 9:16 und TikTok).

Für jedes gewählte Format entsteht eine Kopie des Projekts mit dessen Format- und Export-Preset; das Projekt selbst bleibt
unverändert. Vorhandene Dateien werden nie überschrieben, es wird durchnummeriert.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from . import presets
from .project import Project


class MultiExportError(Exception):
    pass


@dataclass
class Job:
    format_id: str
    label: str
    out: str
    project: Project


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str, default: str = "Video") -> str:
    """Dateiname ohne Zeichen, die Windows nicht erlaubt; ohne Endung .mp4 und ohne Punkt/Leerzeichen am Ende."""
    s = _BAD.sub("_", str(name or "")).strip()
    if s.lower().endswith(".mp4"):
        s = s[:-4]
    s = s.strip(" .")
    if not s or s.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)\d", s.upper()):
        return default
    return s[:120]


def unique_path(folder: Path, stem: str) -> Path:
    p = folder / f"{stem}.mp4"
    n = 2
    while p.exists():
        p = folder / f"{stem}_{n}.mp4"
        n += 1
    return p


def plan(project: Project, format_ids: list[str], folder: str | Path, base: str) -> list[Job]:
    """Legt die Aufträge an (ohne zu exportieren). Reihenfolge wie übergeben, doppelte Formate entfallen."""
    if not project.clips:
        raise MultiExportError("Das Projekt enthält keine Clips.")
    ids: list[str] = []
    for fid in format_ids:
        if fid not in ids:
            ids.append(fid)
    if not ids:
        raise MultiExportError("Kein Format gewählt.")
    folder = Path(folder)
    if not folder.is_dir():
        raise MultiExportError(f"Der Ordner existiert nicht: {folder}")
    stem = safe_name(base, "Mein_Video")
    jobs: list[Job] = []
    taken: set[str] = set()
    for fid in ids:
        fmt = presets.get("formats", fid)
        if not fmt:
            raise MultiExportError(f"Format nicht gefunden: {fid}")
        p = copy.deepcopy(project)
        p.format_id = fid
        exp_id = fmt.get("default_export") or project.export_id
        if exp_id and presets.get("exports", exp_id):
            p.export_id = exp_id
        if fid != project.format_id:
            p.layout = ""                      # eigene Bildanpassung gilt nur für das Format, in dem sie eingestellt wurde
        out = unique_path(folder, f"{stem}_{safe_name(fid)}")
        while str(out) in taken:               # zwei Aufträge im selben Lauf bekommen nie denselben Namen
            out = unique_path(folder, out.stem + "_x")
        taken.add(str(out))
        jobs.append(Job(fid, fmt.get("name", fid), str(out), p))
    return jobs
