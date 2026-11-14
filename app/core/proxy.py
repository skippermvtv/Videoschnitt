"""Proxy-Dateien: kleine, schnell abspielbare Kopien großer Videos für die Vorschau.

Der Export benutzt immer die Originale. Proxys liegen im Cache-Ordner (…/proxies), der Dateiname hängt von Pfad, Größe und
Änderungszeit der Quelle ab; ändert sich die Quelle, entsteht automatisch ein neuer Proxy. Bild, Zeitachse und Ton bleiben
gleich lang wie im Original, nur die Auflösung ist kleiner (höchstens PROXY_HEIGHT) und die Dekodierung leichter.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

from .. import paths
from ..paths import find_binary
from .project import Project, is_image_path

PROXY_HEIGHT = 720
VERSION = "1"                      # ändern, wenn sich die Erzeugung ändert (alte Proxys werden dann nicht mehr benutzt)
HEAVY_LONG_SIDE = 2000             # größer als Full HD gilt als „schwer“
HEAVY_BITRATE = 40_000_000         # bit/s
HEAVY_CODECS = ("hevc", "av1", "vp9", "prores", "dnxhd", "mjpeg")
_NOWINDOW = 0x08000000 if os.name == "nt" else 0


class ProxyError(Exception):
    pass


def proxy_dir() -> Path:
    d = paths.user_dir() / "proxies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def proxy_path(src: str) -> Path:
    try:
        st = Path(src).stat()
        sig = f"{VERSION}|{PROXY_HEIGHT}|{src}|{st.st_size}|{st.st_mtime_ns}"
    except OSError:
        sig = f"{VERSION}|{PROXY_HEIGHT}|{src}"
    return proxy_dir() / (hashlib.sha1(sig.encode("utf-8")).hexdigest()[:20] + ".mp4")


def existing(src: str) -> str:
    """Pfad des fertigen Proxys oder leer, wenn es keinen gibt."""
    if not src or is_image_path(src):
        return ""
    p = proxy_path(src)
    try:
        if p.is_file() and p.stat().st_size > 0:
            return str(p)
    except OSError:
        pass
    return ""


def inspect(src: str) -> dict:
    """Die für die Entscheidung nötigen Eigenschaften: width, height, codec, bitrate, has_audio (0/leer bei Unbekanntem)."""
    r = subprocess.run([find_binary("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", src],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_NOWINDOW, timeout=60)
    if r.returncode != 0:
        raise ProxyError(r.stderr.strip()[-300:] or "Datei konnte nicht gelesen werden")
    data = json.loads(r.stdout or "{}")
    out = {"width": 0, "height": 0, "codec": "", "bitrate": 0, "has_audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not out["width"]:
            out["width"], out["height"] = int(s.get("width", 0)), int(s.get("height", 0))
            out["codec"] = str(s.get("codec_name", ""))
        elif s.get("codec_type") == "audio":
            out["has_audio"] = True
    try:
        out["bitrate"] = int(float(data.get("format", {}).get("bit_rate", 0) or 0))
    except ValueError:
        out["bitrate"] = 0
    return out


def is_heavy(info: dict) -> bool:
    """Lohnt sich ein Proxy? Ja bei mehr als Full HD, schwer dekodierbaren Formaten oder sehr hoher Datenrate."""
    if max(int(info.get("width", 0)), int(info.get("height", 0))) > HEAVY_LONG_SIDE:
        return True
    if str(info.get("codec", "")).lower() in HEAVY_CODECS:
        return True
    return int(info.get("bitrate", 0)) > HEAVY_BITRATE


def command(src: str, out: str, has_audio: bool = True) -> list[str]:
    """FFmpeg-Befehl für den Proxy: höchstens PROXY_HEIGHT hoch, 8 Bit, kurze Bildgruppen (schnelles Springen), gleicher Takt."""
    cmd = [find_binary("ffmpeg"), "-v", "error", "-y", "-nostdin", "-progress", "pipe:1", "-nostats", "-i", src,
           "-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", "0:a:0?"]
    cmd += ["-vf", f"scale=-2:'min({PROXY_HEIGHT},ih)':flags=bilinear,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-g", "12", "-bf", "0",
            "-fps_mode", "passthrough"]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000"]
    cmd += ["-movflags", "+faststart", "-f", "mp4", out]
    return cmd


def make(src: str, on_progress=None, should_cancel=None) -> str:
    """Erzeugt den Proxy (falls es ihn nicht gibt) und gibt seinen Pfad zurück. Während der Arbeit heißt die Datei *.part."""
    from . import exporter
    done = existing(src)
    if done:
        return done
    info = inspect(src)
    dur = 0.0
    try:
        from .project import probe
        dur = probe(src).duration
    except Exception:  # noqa: BLE001
        dur = 0.0
    final = proxy_path(src)
    part = final.with_name(final.stem + ".part.mp4")
    try:
        exporter.run(command(src, str(part), bool(info["has_audio"])), dur or 1.0, on_progress, should_cancel)
        if not part.is_file() or part.stat().st_size == 0:
            raise ProxyError("Der Proxy wurde nicht erzeugt.")
        os.replace(part, final)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    return str(final)


def substitute(project: Project) -> Project:
    """Kopie des Projekts, in der Videos mit fertigem Proxy durch den Proxy ersetzt sind (nur für Vorschau-Rechnungen!).
    Clips mit Stabilisierung behalten das Original (die Analyse gehört zur Originaldatei). Das Original-Projekt bleibt unverändert."""
    p = copy.deepcopy(project)
    for c in p.clips:
        if c.is_image or int(getattr(c, "stabilize", 0) or 0) > 0:
            continue
        pr = existing(c.path)
        if pr:
            c.path = pr
    for o in p.overlays:
        if not o.is_image:
            pr = existing(o.path)
            if pr:
                o.path = pr
    return p


def candidates(project: Project) -> list[str]:
    """Videodateien des Projekts, für die ein Proxy noch fehlt (eindeutig, Reihenfolge der Timeline)."""
    out: list[str] = []
    for src in [c.path for c in project.clips if not c.is_image] + [o.path for o in project.overlays if not o.is_image]:
        if src not in out and os.path.isfile(src) and not existing(src):
            out.append(src)
    return out
