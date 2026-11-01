"""Pfade: funktionieren sowohl im Entwicklungsmodus als auch im PyInstaller-Build."""
import os
import shutil
import sys
from pathlib import Path

from .version import APP_NAME


def bundle_dir() -> Path:
    """Ordner, in dem die mitgelieferten Dateien (presets, fonts, ffmpeg) liegen."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_dir() -> Path:
    """Schreibbarer Ordner des Benutzers (Windows: %APPDATA%\\ClipForge)."""
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def user_presets_dir() -> Path:
    p = user_dir() / "presets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def user_fonts_dir() -> Path:
    p = user_dir() / "fonts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def find_binary(name: str) -> str:
    """Findet ffmpeg/ffprobe: erst mitgeliefert, dann im PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    for cand in (bundle_dir() / "vendor" / "ffmpeg" / exe,
                 bundle_dir() / "vendor" / "ffmpeg" / "bin" / exe):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"{name} wurde nicht gefunden. Im Installer ist FFmpeg enthalten; "
        f"im Entwicklungsmodus bitte FFmpeg installieren und in den PATH legen."
    )
