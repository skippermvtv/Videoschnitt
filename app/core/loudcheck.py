"""Lautheit der fertigen Datei nachmessen (EBU R128, integriert) und für die Anzeige beschreiben."""
from __future__ import annotations

import re
import subprocess

from ..paths import find_binary

_NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_I = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS\s*$", re.M)


def parse_summary(text: str) -> float | None:
    """Der „Summary“-Block von ebur128 enthält „I: -14.0 LUFS“; der letzte Treffer zählt (die Zeilen davor sind Zwischenwerte)."""
    found = _I.findall(text or "")
    return float(found[-1]) if found else None


def measure(path: str, timeout: float = 300.0) -> float | None:
    """Integrierte Lautheit in LUFS oder None (kein Ton, Stille, Fehler)."""
    try:
        r = subprocess.run([find_binary("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128=framelog=quiet",
                            "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=_NOWINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    v = parse_summary(r.stderr)
    return v if v is not None and v > -70.0 else None          # −70 LUFS und leiser ist praktisch Stille


def _de(v: float) -> str:
    return f"{v:.1f}".replace(".", ",").replace("-", "−")


def describe(measured: float | None, goal: float | None = None) -> str:
    """„Lautheit: −13,2 LUFS (Ziel −14,0)“; leer, wenn nicht gemessen werden konnte. goal=None, wenn nicht angeglichen wurde."""
    if measured is None:
        return ""
    s = f"Lautheit: {_de(measured)} LUFS"
    if goal is not None:
        s += f" (Ziel {_de(goal)})"
    return s
