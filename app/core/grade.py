"""Bildkorrektur (Licht, Kontrast, Farbe) pro Clip → FFmpeg-Filterkette.

Ein "Grade" ist ein Dict {schlüssel: wert}. Fehlende Schlüssel gelten als neutral.
Alle Regler laufen von -100 … +100 (Schärfe/Entrauschen 0 … 100, auto 0/1, Farbton -180 … +180).

Seit 1.3 zusätzlich:
  * Farbräder  `lift_r/g/b`, `mid_r/g/b`, `gain_r/g/b` (Schatten, Mitten, Lichter; -100 … +100 je Kanal)
  * Kurven     `curves` = {"m"|"r"|"g"|"b": [[x, y], …]} mit Werten 0 … 1
  * LUT        `lut` = Pfad zu einer .cube/.3dl-Datei, `lut_mix` = Stärke 1 … 100 (fehlt = 100)
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..paths import find_binary, user_luts_dir


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
WHEEL_ZONES = ("lift", "mid", "gain")          # Schatten, Mitten, Lichter
WHEEL_KEYS = [f"{z}_{c}" for z in WHEEL_ZONES for c in "rgb"]
CURVE_CHANNELS = ("m", "r", "g", "b")           # Master, Rot, Grün, Blau
CURVE_MAX_POINTS = 12
LUT_EXTS = (".cube", ".3dl", ".dat", ".m3d")
KEYS = {p.key for p in PARAMS} | {"auto"} | set(WHEEL_KEYS)
EXTRA_KEYS = {"curves", "lut", "lut_mix"}


# --------------------------------------------------------------- Kurven
def normalize_points(points) -> list[list[float]]:
    """Bereinigt eine Kurve: Zahlen 0…1, nach x sortiert, Randpunkte bei x=0 und x=1 vorhanden."""
    pts: list[list[float]] = []
    for p in points or []:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if x != x or y != y:       # NaN
            continue
        pts.append([min(1.0, max(0.0, x)), min(1.0, max(0.0, y))])
    pts.sort(key=lambda q: q[0])
    out: list[list[float]] = []
    for q in pts:
        if out and q[0] - out[-1][0] < 0.01:      # zu nah am Vorgänger
            if q[0] >= 1.0 and out[-1][0] > 0.0:
                out[-1] = q                         # Endpunkt hat Vorrang
            continue
        out.append(q)
    if not out or out[0][0] > 0.0:
        out.insert(0, [0.0, 0.0])
    if out[-1][0] < 1.0:
        if 1.0 - out[-1][0] < 0.01 and len(out) > 1:
            out[-1][0] = 1.0
        else:
            out.append([1.0, 1.0])
    if len(out) > CURVE_MAX_POINTS:
        step = (len(out) - 1) / (CURVE_MAX_POINTS - 1)
        out = [out[round(i * step)] for i in range(CURVE_MAX_POINTS)]
    return out


def curve_is_identity(points) -> bool:
    return all(abs(x - y) < 1e-3 for x, y in normalize_points(points))


def clean_curves(curves) -> dict:
    out = {}
    if isinstance(curves, dict):
        for ch in CURVE_CHANNELS:
            if ch in curves:
                pts = normalize_points(curves[ch])
                if not curve_is_identity(pts):
                    out[ch] = [[round(x, 4), round(y, 4)] for x, y in pts]
    return out


def lut_kind(path: str) -> str:
    """'lut1d' oder 'lut3d' – 1D-Tabellen erkennt man am Kopf der .cube-Datei."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for _ in range(200):
                line = fh.readline()
                if not line:
                    break
                tag = line.strip().upper()
                if tag.startswith("LUT_1D_SIZE"):
                    return "lut1d"
                if tag.startswith("LUT_3D_SIZE"):
                    return "lut3d"
    except OSError:
        pass
    return "lut3d"


def validate_lut(path: str) -> str:
    """Prüft eine LUT-Datei; gibt '' zurück, wenn sie brauchbar aussieht, sonst eine Fehlermeldung."""
    if not os.path.isfile(path):
        return "Die Datei gibt es nicht."
    ext = os.path.splitext(path)[1].lower()
    if ext not in LUT_EXTS:
        return "Dieses Format wird nicht unterstützt (erlaubt: " + ", ".join(LUT_EXTS) + ")."
    if os.path.getsize(path) > 60 * 1024 * 1024:
        return "Die Datei ist zu groß für eine LUT."
    if ext != ".cube":
        return ""                        # .3dl/.dat/.m3d prüft FFmpeg beim Anwenden
    size, kind, rows = 0, "", 0
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                t = line.strip()
                if not t or t.startswith("#"):
                    continue
                up = t.upper()
                if up.startswith("LUT_3D_SIZE") or up.startswith("LUT_1D_SIZE"):
                    try:
                        size = int(t.split()[1])
                    except (IndexError, ValueError):
                        return "Die Größenangabe der LUT ist unlesbar."
                    kind = "3d" if up.startswith("LUT_3D") else "1d"
                    continue
                parts = t.split()
                if len(parts) == 3 and all(re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", x) for x in parts):
                    rows += 1
    except OSError as exc:
        return f"Datei nicht lesbar: {exc}"
    if not kind:
        return "Keine gültige .cube-Datei (LUT_3D_SIZE fehlt)."
    want = size ** 3 if kind == "3d" else size
    if size < 2 or rows != want:
        return f"Die LUT ist unvollständig ({rows} von {want} Werten)."
    return ""


def import_lut(path: str) -> str:
    """Kopiert eine LUT in den Datenordner (sicherer Dateiname, bleibt bei verschobenem Original erhalten)."""
    err = validate_lut(path)
    if err:
        raise ValueError(err)
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(path))[0]).strip("_")[:40] or "lut"
    dest = user_luts_dir() / f"{stem}_{h.hexdigest()[:8]}{os.path.splitext(path)[1].lower()}"
    if not dest.exists():
        shutil.copyfile(path, dest)
    return str(dest)


def clean(grade: dict | None) -> dict:
    """Nur bekannte Schlüssel mit Zahlenwerten, neutrale Werte weglassen."""
    out: dict = {}
    for k, v in (grade or {}).items():
        if k in KEYS:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if abs(v) > 1e-9:
                out[k] = v
    src = grade or {}
    curves = clean_curves(src.get("curves"))
    if curves:
        out["curves"] = curves
    lut = src.get("lut")
    if isinstance(lut, str) and lut.strip():
        out["lut"] = lut.strip()
        try:
            mix = float(src.get("lut_mix", 100))
        except (TypeError, ValueError):
            mix = 100.0
        mix = min(100.0, max(1.0, mix))
        if mix < 99.5:
            out["lut_mix"] = mix
    return out


def is_neutral(grade: dict | None) -> bool:
    return not clean(grade)


def _n(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def esc_path(p: str) -> str:
    """Pfad als Filteroption, ohne Anführungszeichen, gegen beide Auswertungsebenen von FFmpeg geschützt.

    Windows: C:\\Users\\x → C\\\\:/Users/x. Leerzeichen, Klammern, Kommas und Apostroph sind erlaubt.
    """
    p = p.replace("\\", "/")
    p = p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")     # Ebene 2: Filteroptionen
    out = []
    for ch in p:                                                          # Ebene 1: Filtergraph
        out.append("\\" + ch if ch in "\\'[],;" else ch)
    return "".join(out)


def _curve_arg(points) -> str:
    return " ".join(f"{_n(x)}/{_n(y)}" for x, y in normalize_points(points))


def _stages(g: dict) -> tuple[list[str], str, list[str]]:
    """Teilt die Kette in (vor der LUT, LUT-Filter oder '', nach der LUT)."""
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

    # Farbräder: Schatten (lift), Mitten (mid), Lichter (gain) als Farbverschiebung je Kanal
    if any(g.get(k) for k in WHEEL_KEYS):
        opt = []
        for zone, suffix in (("lift", "s"), ("mid", "m"), ("gain", "h")):
            for ch in "rgb":
                val = v(f"{zone}_{ch}")
                if val:
                    opt.append(f"{ch}{suffix}={_n(0.5 * val)}")
        f.append("colorbalance=" + ":".join(opt))

    # Eigene Kurven (Master, Rot, Grün, Blau)
    curves = g.get("curves") or {}
    if curves:
        names = {"m": "master", "r": "red", "g": "green", "b": "blue"}
        f.append("curves=" + ":".join(f"{names[ch]}='{_curve_arg(curves[ch])}'"
                                      for ch in CURVE_CHANNELS if ch in curves))

    if g.get("hue"):
        f.append(f"hue=h={_n(g['hue'])}")
    if g.get("vibrance"):
        f.append(f"vibrance=intensity={_n(1.0 * v('vibrance'))}")

    lut = ""
    path = g.get("lut")
    if path and os.path.isfile(path):
        lut = f"{lut_kind(path)}=file={esc_path(path)}"

    post: list[str] = []
    if g.get("sharpen"):
        post.append(f"unsharp=5:5:{_n(1.5 * v('sharpen'))}:5:5:0")
    return f, lut, post


def filter_chain(grade: dict | None) -> str:
    """Komma-getrennte FFmpeg-Filter (LUT immer mit voller Stärke); leer, wenn nichts zu tun ist."""
    g = clean(grade)
    if not g:
        return ""
    pre, lut, post = _stages(g)
    return ",".join(pre + ([lut] if lut else []) + post)


def apply_label(i: str, o: str, grade: dict | None) -> str:
    """Filtergraph-Teil [i]…[o] für den Export (mit LUT-Mischung, wenn die Stärke unter 100 liegt)."""
    g = clean(grade)
    if not g:
        return f"[{i}]null[{o}]"
    pre, lut, post = _stages(g)
    mix = g.get("lut_mix", 100.0)
    if lut and mix < 99.5:
        first = ",".join(pre + ["split=2[%s_a][%s_b]" % (o, o)]) if pre else "split=2[%s_a][%s_b]" % (o, o)
        parts = [f"[{i}]{first}",
                 f"[{o}_b]{lut}[{o}_c]",
                 f"[{o}_a][{o}_c]blend=all_mode=normal:all_opacity={_n(mix / 100.0)}"
                 + ("," + ",".join(post) if post else "") + f"[{o}]"]
        return ";".join(parts)
    chain = ",".join(pre + ([lut] if lut else []) + post)
    return f"[{i}]{chain or 'null'}[{o}]"


# ----------------------------------------------------------- Vorher/Nachher
def preview_command(path: str, t: float, grade: dict | None, out_png: str, width: int = 360, height: int = 200) -> list[str]:
    """Ein Standbild für die Live-Vorschau: oben Original, unten korrigiert (beide im gleichen Kasten)."""
    after = apply_label("b", "g", grade)
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
