"""Bildkorrektur (Licht, Kontrast, Farbe) pro Clip → FFmpeg-Filterkette.

Ein "Grade" ist ein Dict {schlüssel: wert}. Fehlende Schlüssel gelten als neutral.
Alle Regler laufen von -100 … +100 (Schärfe/Entrauschen 0 … 100, auto 0/1, Farbton -180 … +180).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..paths import find_binary


@dataclass(frozen=True)
class Param:
    key: str
    name: str
    group: str
    min: int = -100
    max: int = 100
    default: int = 0


PARAMS: list[Param] = [
    Param("brightness", "Helligkeit", "Licht"),
    Param("contrast", "Kontrast", "Licht"),
    Param("gamma", "Mitteltöne", "Licht"),
    Param("highlights", "Lichter", "Licht"),
    Param("shadows", "Schatten", "Licht"),
    Param("temperature", "Farbtemperatur (kalt ↔ warm)", "Farbe"),
    Param("tint", "Tönung (grün ↔ magenta)", "Farbe"),
    Param("saturation", "Sättigung", "Farbe"),
    Param("vibrance", "Dynamik (Farben sanft verstärken)", "Farbe"),
    Param("hue", "Farbton verschieben", "Farbe", -180, 180),
    Param("sharpen", "Schärfe", "Detail", 0, 100),
    Param("denoise", "Rauschen reduzieren", "Detail", 0, 100),
]
KEYS = {p.key for p in PARAMS} | {"auto"}


def clean(grade: dict | None) -> dict:
    """Nur bekannte Schlüssel mit Zahlenwerten, neutrale Werte weglassen."""
    out = {}
    for k, v in (grade or {}).items():
        if k in KEYS:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if abs(v) > 1e-9:
                out[k] = v
    return out


def is_neutral(grade: dict | None) -> bool:
    return not clean(grade)


def _n(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def filter_chain(grade: dict | None) -> str:
    """Komma-getrennte FFmpeg-Filter; leerer String, wenn nichts zu tun ist."""
    g = clean(grade)
    if not g:
        return ""
    v = lambda k: g.get(k, 0.0) / 100.0  # noqa: E731  → -1 … +1
    f: list[str] = []

    if g.get("denoise"):
        s = 1.0 + 9.0 * v("denoise")
        f.append(f"hqdn3d=luma_spatial={_n(s)}:chroma_spatial={_n(s * 0.75)}"
                 f":luma_tmp={_n(s * 1.5)}:chroma_tmp={_n(s * 1.1)}")
    if g.get("auto"):
        f.append("normalize=smoothing=24:independence=0")

    # Helligkeit, Kontrast, Mitteltöne, Sättigung in einem eq-Filter
    eq = []
    if g.get("brightness"):
        eq.append(f"brightness={_n(0.25 * v('brightness'))}")
    if g.get("contrast"):
        eq.append(f"contrast={_n(1 + 0.6 * v('contrast'))}")
    if g.get("gamma"):
        eq.append(f"gamma={_n(2 ** (0.8 * v('gamma')))}")
    if g.get("saturation"):
        eq.append(f"saturation={_n(1 + v('saturation'))}")
    if eq:
        f.append("eq=" + ":".join(eq))

    # Lichter und Schatten über eine Gradationskurve
    if g.get("shadows") or g.get("highlights"):
        sy = min(0.45, max(0.05, 0.25 + 0.12 * v("shadows")))
        hy = min(0.95, max(0.55, 0.75 + 0.12 * v("highlights")))
        f.append(f"curves=all='0/0 0.25/{_n(sy)} 0.75/{_n(hy)} 1/1'")

    # Weißabgleich: Temperatur (rot/blau) und Tönung (grün)
    if g.get("temperature") or g.get("tint"):
        rr = 1 + 0.18 * v("temperature")
        bb = 1 - 0.18 * v("temperature")
        gg = 1 - 0.15 * v("tint")
        f.append(f"colorchannelmixer=rr={_n(rr)}:gg={_n(gg)}:bb={_n(bb)}")

    if g.get("hue"):
        f.append(f"hue=h={_n(g['hue'])}")
    if g.get("vibrance"):
        f.append(f"vibrance=intensity={_n(1.0 * v('vibrance'))}")
    if g.get("sharpen"):
        f.append(f"unsharp=5:5:{_n(1.5 * v('sharpen'))}:5:5:0")
    return ",".join(f)


def apply_label(i: str, o: str, grade: dict | None) -> str:
    """Filtergraph-Teil [i]…[o] für den Export."""
    chain = filter_chain(grade)
    return f"[{i}]{chain or 'null'}[{o}]"


# ----------------------------------------------------------- Vorher/Nachher
def preview_command(path: str, t: float, grade: dict | None, out_png: str, width: int = 360, height: int = 200) -> list[str]:
    """Ein Standbild für die Live-Vorschau: oben Original, unten korrigiert (beide im gleichen Kasten)."""
    chain = filter_chain(grade)
    after = f"[b]{chain}[g]" if chain else "[b]null[g]"
    graph = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,split[a][b];{after};"
             f"[a][g]vstack=inputs=2,format=rgb24[o]")
    return [find_binary("ffmpeg"), "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", path,
            "-filter_complex", graph, "-map", "[o]", "-frames:v", "1", out_png]


def render_preview(path: str, t: float, grade: dict | None, width: int = 360, height: int = 200) -> str:
    """Rendert das Vorher/Nachher-Bild und gibt den PNG-Pfad zurück (wirft bei Fehler RuntimeError)."""
    out = os.path.join(tempfile.mkdtemp(prefix="clipforge_grade_"), "preview.png")
    flags = 0x08000000 if os.name == "nt" else 0
    r = subprocess.run(preview_command(path, t, grade, out, width, height), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=flags, timeout=30)
    if r.returncode != 0 or not Path(out).exists():
        raise RuntimeError(r.stderr.strip()[-400:] or "Vorschau fehlgeschlagen")
    return out
