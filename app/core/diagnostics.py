"""Fehlerprotokoll, Absturz-Hook und Diagnosebericht.

Alles landet in %APPDATA%\\FATE VIDEOSCHNITT\\logs\\videoschnitt.log. Bei einem Absturz oder einem
unerwarteten Fehler schreibt das Programm den vollständigen Fehlertext dorthin und zeigt
einen Dialog, in dem man den Bericht mit einem Klick kopieren kann.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import platform
import subprocess
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from .. import paths
from ..version import APP_NAME, VERSION

_NOWINDOW = 0x08000000
_LOG = logging.getLogger("fate_videoschnitt")
_state: dict = {"fault_file": None, "ready": False}


def log_dir() -> Path:
    d = paths.user_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file() -> Path:
    return log_dir() / "videoschnitt.log"


def setup_logging() -> Path:
    """Richtet die Logdatei ein (rotierend, 3 × 512 kB). Mehrfaches Aufrufen ist harmlos."""
    f = log_file()
    if _state["ready"]:
        return f
    _LOG.setLevel(logging.INFO)
    h = RotatingFileHandler(f, maxBytes=512_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _LOG.addHandler(h)
    _LOG.propagate = False
    try:  # harte Abstürze (z. B. in Qt) landen in einer eigenen Datei
        ff = open(log_dir() / "crash.txt", "a", encoding="utf-8")  # noqa: SIM115 - bleibt offen
        faulthandler.enable(ff)
        _state["fault_file"] = ff
    except (OSError, RuntimeError, ValueError):
        pass
    _state["ready"] = True
    _LOG.info("%s %s gestartet (Python %s, %s)", APP_NAME, VERSION, platform.python_version(), platform.platform())
    return f


def log(msg: str, *args) -> None:
    _LOG.info(msg, *args)


def log_error(msg: str, *args) -> None:
    _LOG.error(msg, *args)


def install_exception_hooks(on_error: Callable[[str], None] | None = None) -> None:
    """Fängt unbehandelte Fehler (Hauptthread und Threads), protokolliert sie und meldet sie weiter."""
    def report(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        _LOG.error("Unbehandelter Fehler:\n%s", text)
        if on_error:
            try:
                on_error(text)
            except Exception:  # noqa: BLE001 - der Hook darf nie selbst abstürzen
                pass

    sys.excepthook = report
    threading.excepthook = lambda a: report(a.exc_type, a.exc_value, a.exc_traceback)


def read_log_tail(max_chars: int = 6000) -> str:
    try:
        t = log_file().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(noch kein Protokoll vorhanden)"
    return t[-max_chars:]


def crash_file_text(max_chars: int = 3000) -> str:
    try:
        return (log_dir() / "crash.txt").read_text(encoding="utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


# ------------------------------------------------------------------ Diagnose
def _run(cmd: list[str], timeout: float = 25) -> tuple[int, str]:
    flags = _NOWINDOW if os.name == "nt" else 0
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=flags)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)


def test_encoders() -> dict[str, tuple[bool, str]]:
    """Probiert jeden Encoder mit einem 0,3-s-Testbild aus. {Name: (geht, Meldung)}."""
    out: dict[str, tuple[bool, str]] = {}
    try:
        ff = paths.find_binary("ffmpeg")
    except FileNotFoundError as exc:
        return {"ffmpeg": (False, str(exc))}
    for enc in ("libx264", "h264_nvenc", "h264_qsv", "h264_amf"):
        rc, msg = _run([ff, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.3",
                        "-c:v", enc, "-f", "null", "-"])
        out[enc] = (rc == 0, "" if rc == 0 else (msg.splitlines()[-1] if msg else f"Code {rc}"))
    return out


def ffmpeg_version() -> str:
    try:
        rc, txt = _run([paths.find_binary("ffmpeg"), "-version"], 10)
    except FileNotFoundError as exc:
        return f"nicht gefunden ({exc})"
    return txt.splitlines()[0] if txt else f"Fehler (Code {rc})"


def build_report(with_encoder_test: bool = True, with_log: bool = True) -> str:
    """Text, den man mir (oder dem Support) schicken kann. Enthält keine Projektinhalte und keine Dateipfade außer dem Datenordner."""
    from . import subtitles
    L = [f"{APP_NAME} {VERSION}", f"Windows/System: {platform.platform()}", f"Python: {platform.python_version()}",
         f"FFmpeg: {ffmpeg_version()}"]
    try:
        from PySide6 import __version__ as qtv
        L.append(f"PySide6: {qtv}")
    except ImportError:
        L.append("PySide6: nicht geladen")
    if with_encoder_test:
        L.append("Encoder-Test:")
        for name, (ok, msg) in test_encoders().items():
            L.append(f"  {name}: {'OK' if ok else 'nicht verfügbar'}{'' if ok or not msg else ' – ' + msg}")
    w = subtitles.find_whisper()
    L.append("Spracherkennung: " + (f"bereit ({Path(w[1]).name})" if w else "nicht eingerichtet"))
    L.append(f"Datenordner: {paths.user_dir()}")
    if with_log:
        crash = crash_file_text()
        if crash.strip():
            L += ["", "--- crash.txt ---", crash]
        L += ["", "--- Protokoll (Ende) ---", read_log_tail()]
    return "\n".join(L)
