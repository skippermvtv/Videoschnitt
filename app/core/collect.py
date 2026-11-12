"""Projekt sammeln: alle benutzten Dateien in einen Ordner oder ZIP kopieren, damit das Projekt umziehen kann.

Im gesammelten Projekt stehen die Pfade relativ ("Medien/clip.mp4"); beim Öffnen werden sie auf den Ordner der Projektdatei
bezogen (siehe absolutize, aufgerufen von Project.load).
"""
from __future__ import annotations

import os
import re
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

from .. import paths
from .project import Project

MEDIA_DIR = "Medien"
CHUNK = 8 * 1024 * 1024


class CollectError(Exception):
    pass


class Cancelled(CollectError):
    pass


def _refs(project: Project):
    """Alle Stellen im Projekt, die auf eine Datei zeigen: Liste aus (Pfad, Setzer-Funktion)."""
    out = []

    def add(path, setter):
        if isinstance(path, str) and path.strip():
            out.append((path, setter))

    for c in project.clips:
        add(c.path, lambda v, c=c: setattr(c, "path", v))
        add(c.key_bg, lambda v, c=c: setattr(c, "key_bg", v))
        if isinstance(c.grade, dict):
            add(c.grade.get("lut"), lambda v, c=c: c.grade.__setitem__("lut", v))
    for a in project.audio_clips:
        add(a.path, lambda v, a=a: setattr(a, "path", v))
    for o in project.overlays:
        add(o.path, lambda v, o=o: setattr(o, "path", v))
    add(project.watermark, lambda v: setattr(project, "watermark", v))
    for t in project.texts:
        add(t.font, lambda v, t=t: setattr(t, "font", v))
    add(project.sub_style.font, lambda v: setattr(project.sub_style, "font", v))
    bundle = str(paths.bundle_dir().resolve()).lower()
    return [(p, s) for p, s in out if not _is_bundled_font(p, bundle)]


def _is_bundled_font(path: str, bundle_lower: str) -> bool:
    """Schriften, die zum Programm gehören, sind auf jedem Rechner da und werden nicht mitkopiert."""
    if not os.path.isabs(path):
        return False
    try:
        return str(Path(path).resolve()).lower().startswith(bundle_lower) and Path(path).suffix.lower() in (".ttf", ".otf")
    except OSError:
        return False


def used_files(project: Project) -> list[str]:
    """Alle benutzten Dateien (eindeutig, in Reihenfolge des Auftretens), auch fehlende."""
    seen: list[str] = []
    for p, _s in _refs(project):
        if p not in seen:
            seen.append(p)
    return seen


def summary(project: Project) -> dict:
    files = used_files(project)
    ok = [f for f in files if os.path.isfile(f)]
    return {"files": ok, "missing": [f for f in files if f not in ok], "bytes": sum(os.path.getsize(f) for f in ok)}


def _plan(files: list[str]) -> dict[str, str]:
    """Ordnet jeder Datei einen eindeutigen Namen in Medien/ zu (gleiche Dateinamen bekommen _2, _3 …)."""
    names: dict[str, str] = {}
    taken: set[str] = set()
    for f in files:
        base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(f).name) or "datei"
        stem, ext = os.path.splitext(base)
        cand, n = base, 2
        while cand.lower() in taken:
            cand = f"{stem}_{n}{ext}"
            n += 1
        taken.add(cand.lower())
        names[f] = f"{MEDIA_DIR}/{cand}"
    return names


def _copy_chunks(src: str, dst, progress: Callable[[int], None] | None, cancel: Callable[[], bool] | None) -> None:
    with open(src, "rb") as fi:
        while True:
            if cancel and cancel():
                raise Cancelled("Abgebrochen.")
            buf = fi.read(CHUNK)
            if not buf:
                break
            dst.write(buf)
            if progress:
                progress(len(buf))


def collect(project: Project, target: str, as_zip: bool = False, name: str = "Projekt",
            on_progress: Callable[[float, str], None] | None = None,
            should_cancel: Callable[[], bool] | None = None) -> dict:
    """Kopiert alle vorhandenen Dateien und legt die Projektdatei mit relativen Pfaden daneben.

    as_zip=False: `target` ist ein Ordner (wird angelegt); as_zip=True: `target` ist die ZIP-Datei.
    Fehlende Dateien werden übersprungen und gemeldet; ihre Pfade bleiben im Projekt unverändert.
    Gibt {"files": n, "bytes": b, "missing": [...], "project": Pfad} zurück. Das übergebene Projekt bleibt unverändert."""
    info = summary(project)
    files = info["files"]
    names = _plan(files)
    total = max(1, info["bytes"])
    clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "Projekt"
    proj_file = clean_name + ".cforge"

    p2 = Project.from_json(project.to_json())
    for path, setter in _refs(p2):
        if path in names:
            setter(names[path])
    text = p2.to_json()

    done = 0

    def tick(n: int, label: str = ""):
        nonlocal done
        done += n
        if on_progress:
            on_progress(min(1.0, done / total), label)

    if as_zip:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        part = str(target) + ".teil"
        try:
            with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
                for f in files:
                    with zf.open(names[f], "w", force_zip64=True) as dst:
                        _copy_chunks(f, dst, lambda n, f=f: tick(n, Path(f).name), should_cancel)
                zf.writestr(proj_file, text)
            os.replace(part, target)
        except BaseException:
            if os.path.exists(part):
                os.remove(part)
            raise
        return {"files": len(files), "bytes": info["bytes"], "missing": info["missing"], "project": str(target)}

    dest = Path(target)
    free = shutil.disk_usage(dest.parent if dest.parent.exists() else Path.home()).free
    if info["bytes"] > free:
        raise CollectError(f"Auf dem Ziel ist zu wenig Platz frei (nötig: {info['bytes'] / 1e6:.0f} MB, frei: {free / 1e6:.0f} MB).")
    fresh = not dest.exists()
    (dest / MEDIA_DIR).mkdir(parents=True, exist_ok=True)
    try:
        for f in files:
            out = dest / names[f]
            with open(out, "wb") as dst:
                _copy_chunks(f, dst, lambda n, f=f: tick(n, Path(f).name), should_cancel)
        (dest / proj_file).write_text(text, encoding="utf-8")
    except BaseException:
        if fresh:                                   # halb fertigen Ordner nicht liegen lassen
            shutil.rmtree(dest, ignore_errors=True)
        raise
    return {"files": len(files), "bytes": info["bytes"], "missing": info["missing"], "project": str(dest / proj_file)}


def absolutize(project: Project, base: str | Path) -> int:
    """Macht relative Pfade (Medien/…) zu absoluten, bezogen auf den Ordner der Projektdatei. Gibt die Zahl umgesetzter Pfade zurück."""
    n = 0
    for path, setter in _refs(project):
        if not (os.path.isabs(path) or re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith(("\\\\", "/"))):
            setter(str(Path(base).joinpath(*re.split(r"[\\/]", path))))
            n += 1
    return n
