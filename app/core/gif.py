"""Animiertes GIF: Das Projekt wird klein als Zwischenvideo gerechnet, daraus entsteht das GIF mit eigener Farbpalette."""
from __future__ import annotations

from pathlib import Path

from .. import paths
from . import presets
from .project import Project

MAX_SECONDS = 30.0                     # längere GIFs werden riesig und ruckeln in Chat-Programmen
WIDTHS = (320, 480, 640, 800)
FPS_CHOICES = (8, 10, 12, 15, 20)
DEFAULT_WIDTH = 480
DEFAULT_FPS = 12


def size_for(project: Project, width: int) -> tuple[int, int]:
    """Bildgröße des GIFs (Breite, Höhe) – Seitenverhältnis des Projektformats, beide gerade."""
    fmt = presets.get("formats", project.format_id) or {"width": 1920, "height": 1080}
    w = max(16, int(width) // 2 * 2)
    h = max(2, round(w * int(fmt["height"]) / int(fmt["width"]) / 2) * 2)
    return w, h


def length_for(project: Project, limit: float = MAX_SECONDS) -> tuple[float, bool]:
    """(Länge in Sekunden, wurde gekürzt?)"""
    d = max(0.1, project.duration)
    return (limit, True) if d > limit else (d, False)


def gif_command(src: str, out: str, width: int, fps: int, loop: bool = True) -> list[str]:
    """Zwei Schritte in einem Aufruf: Palette aus dem ganzen Clip berechnen und das GIF damit schreiben."""
    fps = max(1, min(30, int(fps)))
    vf = (f"fps={fps},scale={max(16, int(width))}:-2:flags=lanczos,split[a][b];"
          "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
    return [paths.find_binary("ffmpeg"), "-hide_banner", "-y", "-progress", "pipe:1", "-nostats", "-i", src,
            "-an", "-filter_complex", vf, "-loop", "0" if loop else "-1", out]


def describe(project: Project, width: int, fps: int) -> str:
    """Kurzer Hinweis im Dialog: Größe, Länge, grobe Dateigröße."""
    w, h = size_for(project, width)
    secs, cut = length_for(project)
    est = w * h * fps * secs * 0.045 / 1_000_000          # grobe Erfahrung: ~0,045 Byte je Pixel und Bild
    text = f"{w}×{h} Pixel, {secs:.1f} s, {fps} Bilder/s – etwa {max(0.1, est):.1f} MB"
    if cut:
        text += f"\nDas Projekt ist länger als {int(MAX_SECONDS)} s: nur die ersten {int(MAX_SECONDS)} s werden ein GIF."
    return text


def default_name(path: str) -> str:
    p = Path(path)
    return str(p if p.suffix.lower() == ".gif" else p.with_suffix(".gif"))
