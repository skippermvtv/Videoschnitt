"""Vorschaubilder für die Übergangsliste: Mitte des Übergangs zwischen zwei Testbildern (zwischengespeichert)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import paths
from ..paths import find_binary

W, H = 160, 90
_NOWINDOW = 0x08000000 if os.name == "nt" else 0
_VERSION = "v1"


def thumb_path(trans_id: str) -> Path:
    d = paths.user_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in trans_id)
    return d / f"trans_{safe}_{_VERSION}.png"


def make_thumb(trans_id: str, xfade: str) -> str:
    """PNG-Pfad des Vorschaubilds (erzeugt es bei Bedarf); wirft RuntimeError bei Fehlern."""
    out = thumb_path(trans_id)
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    cmd = [find_binary("ffmpeg"), "-v", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=10:duration=1.2",
           "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=10:duration=1.2,negate,hue=h=110",
           "-filter_complex", f"[0][1]xfade=transition={xfade}:duration=1:offset=0.1,format=rgb24[v]",
           "-map", "[v]", "-ss", "0.55", "-frames:v", "1", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=_NOWINDOW, timeout=60)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        try:
            out.unlink()
        except OSError:
            pass
        raise RuntimeError(r.stderr.strip()[-300:] or "Übergangsbild fehlgeschlagen")
    return str(out)
