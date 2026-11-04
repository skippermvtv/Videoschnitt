"""Vorschaubilder für die Medienbibliothek (ein Standbild je Datei, zwischengespeichert)."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .. import paths
from ..paths import find_binary

THUMB_W, THUMB_H = 192, 108
_NOWINDOW = 0x08000000 if os.name == "nt" else 0


def thumb_path(src: str) -> Path:
    """Zwischenspeicher-Datei; ändert sich die Quelldatei (Größe/Zeit), ergibt sich ein neuer Name."""
    try:
        st = Path(src).stat()
        sig = f"{src}|{st.st_size}|{st.st_mtime_ns}"
    except OSError:
        sig = src
    d = paths.user_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(sig.encode("utf-8")).hexdigest()[:20] + ".png")


def make_thumb(src: str, duration: float = 0.0, is_image: bool = False) -> str:
    """Erzeugt (oder findet) das Vorschaubild und gibt den PNG-Pfad zurück; wirft RuntimeError bei Fehlern."""
    out = thumb_path(src)
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    vf = (f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=decrease,"
          f"pad={THUMB_W}:{THUMB_H}:(ow-iw)/2:(oh-ih)/2:0x0b0c0f")
    cmd = [find_binary("ffmpeg"), "-v", "error", "-y"]
    if not is_image:
        cmd += ["-ss", f"{min(1.0, max(0.0, duration / 3.0)):.2f}"]
    cmd += ["-i", src, "-frames:v", "1", "-vf", vf, str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=_NOWINDOW, timeout=60)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        try:
            out.unlink()
        except OSError:
            pass
        raise RuntimeError(r.stderr.strip()[-300:] or "Vorschaubild fehlgeschlagen")
    return str(out)
