"""Wellenform einer Audiodatei als PNG mit durchsichtigem Hintergrund (für die Timeline)."""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from ..paths import find_binary

_NOWINDOW = 0x08000000
WIDTH, HEIGHT = 1600, 60


def cache_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "clipforge_wave"
    d.mkdir(parents=True, exist_ok=True)
    return d


def render(path: str, width: int = WIDTH, height: int = HEIGHT) -> str:
    """Erzeugt (oder findet im Zwischenspeicher) die Wellenform der ganzen Datei; gibt den PNG-Pfad zurück."""
    st = os.stat(path)
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}|{width}x{height}".encode("utf-8")).hexdigest()[:16]
    out = cache_dir() / f"{key}.png"
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    graph = (f"[0:a:0]aformat=channel_layouts=mono,showwavespic=s={width}x{height}:colors=white:scale=sqrt,"
             f"format=rgba,colorkey=black:0.12:0.1[w]")
    cmd = [find_binary("ffmpeg"), "-v", "error", "-y", "-i", path, "-filter_complex", graph,
           "-map", "[w]", "-frames:v", "1", str(out)]
    flags = _NOWINDOW if os.name == "nt" else 0
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=flags)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(r.stderr.strip() or "Wellenform konnte nicht erzeugt werden")
    return str(out)
