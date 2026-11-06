"""Ton verbessern: „Rauschen entfernen“ (FFmpeg afftdn) und „Sprache klarer“ (Tiefen weg, Präsenz anheben).

Beides sind Regler 0 (aus) … 100 (stark) pro Clip bzw. Audioblock. Die Filterkette steht direkt nach dem Einlesen
des Tons, noch vor Tempo, Rückwärts und Lautstärke.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..paths import find_binary

_NOWINDOW = 0x08000000 if os.name == "nt" else 0
DEFAULT_FLOOR = -45          # dB, wenn sich der Rauschpegel nicht messen lässt
MAX_SCAN = 120.0             # so viele Sekunden werden höchstens vermessen
_floor_cache: dict[tuple, int] = {}


def _lvl(v) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return 0


def denoise_params(level: int, floor: int | None = None) -> tuple[float, int]:
    """(Rauschminderung in dB, Rauschpegel in dB) für Stärke 1…100. Der Pegel ist gemessen (sonst −45 dB)."""
    s = _lvl(level)
    nf = DEFAULT_FLOOR if floor is None else int(floor)
    return round(6.0 + s * 0.26, 1), max(-80, min(-20, nf))        # 6…32 dB


def noise_floor(path: str, in_pt: float = 0.0, out_pt: float = 0.0) -> int:
    """Misst den Rauschpegel (dBFS) einer Tonspur: die leisesten 10 % kurzer Stücke. afftdn arbeitet nur gut, wenn
    ihm der ungefähre Pegel des Rauschens genannt wird (zu hoch oder zu niedrig angesetzt wirkt er kaum)."""
    try:
        st = Path(path).stat()
        key = (path, st.st_size, st.st_mtime_ns, round(in_pt, 2), round(out_pt, 2))
    except OSError:
        return DEFAULT_FLOOR
    if key in _floor_cache:
        return _floor_cache[key]
    val = DEFAULT_FLOOR
    try:
        import numpy as np
        span = min(MAX_SCAN, out_pt - in_pt) if out_pt > in_pt else MAX_SCAN
        cmd = [find_binary("ffmpeg"), "-v", "error", "-ss", f"{max(0.0, in_pt):.3f}", "-t", f"{span:.3f}", "-i", path,
               "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]
        r = subprocess.run(cmd, capture_output=True, creationflags=_NOWINDOW, timeout=120)
        x = np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)
        n = 2400                                                     # 50-ms-Stücke
        if len(x) >= 4 * n:
            blocks = x[:len(x) // n * n].reshape(-1, n)
            level = 10.0 * np.log10(np.mean(blocks * blocks, axis=1) + 1e-12)
            val = int(round(float(np.percentile(level, 10))))
    except Exception:  # noqa: BLE001  – Messung ist nur eine Hilfe, der Export darf daran nie scheitern
        val = DEFAULT_FLOOR
    val = max(-80, min(-20, val))
    _floor_cache[key] = val
    return val


def voice_params(level: int) -> tuple[int, float]:
    """(Hochpass in Hz, Anhebung bei 3 kHz in dB) für Stärke 1…100."""
    s = _lvl(level)
    return int(round(70 + s * 0.7)), round(s * 0.06, 1)            # 70…140 Hz; 0…6 dB


def chain(denoise: int = 0, voice: int = 0, floor: int | None = None) -> str:
    """Filterkette (ohne führendes Komma); leer, wenn nichts eingestellt ist. `floor` = gemessener Rauschpegel."""
    parts: list[str] = []
    d, v = _lvl(denoise), _lvl(voice)
    if d > 0:
        nr, nf = denoise_params(d, floor)
        parts.append(f"afftdn=nr={nr}:nf={nf}")
    if v > 0:
        hz, gain = voice_params(v)
        parts.append(f"highpass=f={hz}")
        parts.append(f"equalizer=f=3000:t=q:w=0.8:g={gain}")
    return ",".join(parts)
