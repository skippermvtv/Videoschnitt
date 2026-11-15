"""Stapel-Export: mehrere gespeicherte Projekte (.cforge) in einem Rutsch exportieren, jedes in den gewählten Formaten. Ohne Qt.

Die Projekte werden nur gelesen, nie verändert oder gespeichert. Projekte, die sich nicht lesen lassen, leer sind oder deren Dateien fehlen,
werden mit Hinweis übersprungen; die übrigen laufen. Vorhandene Dateien werden nie überschrieben, es wird durchnummeriert.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import multiexport, presets
from .multiexport import Job, MultiExportError
from .project import Project

OWN_FORMAT = "own"                  # „Format wie im Projekt“


@dataclass
class Item:
    file: str
    name: str                       # Dateiname ohne Endung (für die Ausgabedatei)
    project: Project | None = None
    problem: str = ""               # leer = bereit


@dataclass
class Plan:
    jobs: list[Job] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_item(file: str) -> Item:
    p = Path(file)
    item = Item(str(p), multiexport.safe_name(p.stem, "Projekt"))
    try:
        item.project = Project.load(str(p))
    except Exception as exc:  # noqa: BLE001
        item.problem = f"nicht lesbar ({str(exc)[:120]})"
        return item
    if not item.project.clips:
        item.problem = "enthält keine Clips"
        return item
    gone = [x for x in item.project.missing_paths()]
    if gone:
        more = f" und {len(gone) - 1} weitere" if len(gone) > 1 else ""
        item.problem = f"Datei fehlt: {Path(gone[0]).name}{more}"
    return item


def load_items(files: list[str]) -> list[Item]:
    """Lädt die Projekte; doppelte Dateien entfallen, die Reihenfolge bleibt."""
    seen: set[str] = set()
    items: list[Item] = []
    for f in files:
        key = os.path.normcase(os.path.abspath(f))
        if key in seen:
            continue
        seen.add(key)
        items.append(load_item(f))
    return items


def find_projects(folder: str) -> list[str]:
    """Alle .cforge-Dateien direkt in einem Ordner, alphabetisch."""
    d = Path(folder)
    if not d.is_dir():
        return []
    return sorted((str(x) for x in d.iterdir() if x.is_file() and x.suffix.lower() == ".cforge"), key=lambda s: s.lower())


def plan(items: list[Item], format_ids: list[str], folder: str | Path) -> Plan:
    """Aufträge für alle brauchbaren Projekte. `format_ids` darf OWN_FORMAT („wie im Projekt“) enthalten."""
    ids: list[str] = []
    for fid in format_ids:
        if fid not in ids:
            ids.append(fid)
    if not ids:
        raise MultiExportError("Kein Format gewählt.")
    for fid in ids:
        if fid != OWN_FORMAT and not presets.get("formats", fid):
            raise MultiExportError(f"Format nicht gefunden: {fid}")
    folder = Path(folder)
    if not folder.is_dir():
        raise MultiExportError(f"Der Ordner existiert nicht: {folder}")
    res = Plan()
    taken: set[str] = set()
    ready = [it for it in items if it.project is not None and not it.problem]
    for it in items:
        if it.problem:
            res.notes.append(f"{Path(it.file).name}: übersprungen – {it.problem}")
    if not ready:
        raise MultiExportError("Kein Projekt ist exportierbar.\n" + "\n".join(res.notes))
    for it in ready:
        assert it.project is not None
        proj = it.project
        stab = sum(1 for c in proj.clips if int(getattr(c, "stabilize", 0) or 0) > 0 and not c.is_image)
        if stab:
            res.notes.append(f"{Path(it.file).name}: {stab} Clip(s) mit Stabilisierung – ohne vorherige Analyse gilt die einfache Variante "
                             "(für die beste Qualität das Projekt einmal öffnen und normal exportieren).")
        real = [fid for fid in ids if fid != OWN_FORMAT]
        own_first = ids.index(OWN_FORMAT) if OWN_FORMAT in ids else -1
        jobs: list[Job] = []
        if real:
            jobs = multiexport.plan(proj, real, folder, it.name)
        if own_first >= 0:
            own = copy.deepcopy(proj)
            fmt = presets.get("formats", proj.format_id) or {}
            out = multiexport.unique_path(folder, f"{it.name}_{multiexport.safe_name(proj.format_id)}")
            job = Job(proj.format_id, fmt.get("name", proj.format_id), str(out), own)
            if any(j.format_id == proj.format_id for j in jobs):
                job = None                          # dasselbe Format ist schon dabei
            if job is not None:
                jobs.insert(min(own_first, len(jobs)), job)
        for j in jobs:
            out = Path(j.out)
            while str(out) in taken or out.exists():   # auch über Projekte hinweg nie derselbe Name
                out = out.with_name(out.stem + "_x" + out.suffix)
            taken.add(str(out))
            j.out = str(out)
            j.label = f"{it.name}: {j.label}"
            res.jobs.append(j)
    return res
