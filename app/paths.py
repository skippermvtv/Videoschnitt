"""Pfade: funktionieren sowohl im Entwicklungsmodus als auch im PyInstaller-Build."""
import os
import shutil
import sys
from pathlib import Path

from .version import DATA_DIR_NAME, LEGACY_DATA_DIR_NAME


def bundle_dir() -> Path:
    """Ordner, in dem die mitgelieferten Dateien (presets, fonts, ffmpeg) liegen."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_dir() -> Path:
    """Schreibbarer Ordner des Benutzers (Windows: %APPDATA%\\FATE VIDEOSCHNITT).

    Gab es bisher den Ordner „ClipForge“, wird er beim ersten Start umbenannt – Einstellungen, eigene Presets,
    Schriften, Autosave und die Spracherkennung bleiben erhalten. Klappt das nicht, wird der alte Ordner weiterverwendet.
    """
    base = Path(os.environ.get("APPDATA") or str(Path.home() / ".config"))
    p = base / DATA_DIR_NAME
    old = base / LEGACY_DATA_DIR_NAME
    if not p.exists() and old.is_dir():
        try:
            old.rename(p)
        except OSError:
            p = old
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


def resolve_font(path: str) -> str:
    """Findet eine Schriftdatei auch dann, wenn sie umbenannt oder verschoben wurde (alte Projekte).

    Gibt den Pfad zurück, wenn er existiert; sonst die gleichnamige Datei aus den Schriftordnern des Programms
    (die frühere „ClipForgeMetal.ttf“ heißt jetzt „FateMetal.ttf“); sonst "" (dann gilt die Standardschrift).
    """
    if not path or os.path.exists(path):
        return path
    name = Path(path.replace("\\", "/")).name
    name = {"clipforgemetal.ttf": "FateMetal.ttf"}.get(name.lower(), name)
    for folder in (bundle_dir() / "fonts", user_fonts_dir()):
        cand = folder / name
        if cand.exists():
            return str(cand)
    return ""
