"""Vorschau-Zwischenspeicher: gleiche Projektstände werden nicht erneut gerendert."""
from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path

from .project import Project

PREVIEW_LENGTHS = [(8.0, "8 Sekunden"), (20.0, "20 Sekunden"), (60.0, "1 Minute"), (0.0, "Bis zum Ende")]
PREVIEW_QUALITIES = [(240, "Sehr schnell (240p)"), (360, "Schnell (360p)"), (540, "Normal (540p)"), (720, "Gut (720p)")]


def cache_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "clipforge_preview"
    d.mkdir(parents=True, exist_ok=True)
    return d


def key(project: Project, start: float, length: float, height: int) -> str:
    """Hängt vom ganzen Projektstand ab – jede Änderung (auch an Quelldateien) ergibt einen neuen Schlüssel."""
    parts = [project.to_json(), f"{start:.2f}", f"{length:.2f}", str(height)]
    for path in sorted({c.path for c in project.clips} | {a.path for a in project.audio_clips}
                       | {o.path for o in project.overlays}):
        try:
            st = Path(path).stat()
            parts.append(f"{path}|{st.st_size}|{st.st_mtime_ns}")
        except OSError:
            parts.append(path)
    if any(int(getattr(c, "stabilize", 0) or 0) > 0 for c in project.clips):      # Analyse fertig? Dann sieht das Bild anders aus
        from . import stabilize
        parts.append("stab:" + "".join("1" if stabilize.lookup(c.path, c.in_pt, c.out_pt) else "0"
                                       for c in project.clips if getattr(c, "stabilize", 0) and not c.is_image))
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:20]


def path_for(project: Project, start: float, length: float, height: int) -> Path:
    return cache_dir() / f"{key(project, start, length, height)}.mp4"


def cleanup(max_files: int = 12, max_age_days: float = 2.0) -> int:
    """Alte Vorschau-Dateien löschen; gibt die Anzahl gelöschter Dateien zurück."""
    files = sorted(cache_dir().glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    limit = time.time() - max_age_days * 86400
    for i, f in enumerate(files):
        try:
            if i >= max_files or f.stat().st_mtime < limit:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed
