"""Einrichtung der Spracherkennung: lädt whisper.cpp und ein Sprachmodell in %APPDATA%\\FATE VIDEOSCHNITT\\whisper.

Alle Adressen lassen sich als Parameter überschreiben (die Tests nutzen einen lokalen Server).
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from ..version import APP_NAME, VERSION
from . import subtitles

MODELS = {
    # Name: (Dateiname, ungefähre Größe in MB, Beschreibung)
    "tiny": ("ggml-tiny.bin", 78, "sehr schnell, einfache Qualität"),
    "base": ("ggml-base.bin", 148, "schnell, gute Qualität (empfohlen)"),
    "small": ("ggml-small.bin", 488, "langsamer, bessere Qualität"),
}
MODEL_URL = "https://huggingface.co/ggml-org/whisper.cpp/resolve/main/{file}"
RELEASE_API = "https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"
BIN_ASSET = "whisper-bin-x64.zip"


class Cancelled(Exception):
    pass


def _open(url: str, timeout: float = 20.0):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{VERSION}"}), timeout=timeout)


def download_file(url: str, dest: Path, progress: Callable[[float], None] | None = None,
                  cancelled: Callable[[], bool] | None = None, min_bytes: int = 1) -> Path:
    """Lädt in eine .part-Datei und benennt erst am Ende um – eine abgebrochene Datei wird so nie als fertig erkannt.

    Prüft, dass die empfangene Größe zur angekündigten passt.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    got = 0
    try:
        with _open(url) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                if cancelled and cancelled():
                    raise Cancelled()
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress and total:
                    progress(min(1.0, got / total))
        if total and got != total:
            raise RuntimeError(f"Download unvollständig ({got} von {total} Bytes).")
        if got < min_bytes:
            raise RuntimeError(f"Die heruntergeladene Datei ist zu klein ({got} Bytes).")
        os.replace(part, dest)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    if progress:
        progress(1.0)
    return dest


def download_model(name: str = "base", url: str | None = None, progress=None, cancelled=None,
                   min_bytes: int | None = None) -> Path:
    if name not in MODELS:
        raise ValueError(f"Unbekanntes Modell: {name}")
    fn, mb, _ = MODELS[name]
    target = subtitles.whisper_dir() / fn
    if min_bytes is None:
        min_bytes = int(mb * 1_000_000 * 0.9)  # Schutz vor Fehlerseiten statt Modell
    return download_file(url or MODEL_URL.format(file=fn), target, progress, cancelled, min_bytes)


def safe_extract(zip_path: Path, dest: Path) -> list[Path]:
    """Entpackt ohne Pfadtricks (kein '..', keine absoluten Pfade)."""
    out = []
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest != target and dest not in target.parents:
                raise RuntimeError(f"Unsicherer Pfad im Archiv: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            out.append(target)
    return out


def find_program_asset(api_url: str = RELEASE_API) -> tuple[str, str]:
    """(Download-Adresse, Dateiname) des Windows-Programms aus dem neuesten whisper.cpp-Release."""
    with _open(api_url) as r:
        data = json.loads(r.read().decode("utf-8"))
    import re
    assets = data.get("assets", [])
    for a in assets:  # erst der erwartete Name, dann ähnliche Namen (ohne CUDA-Varianten)
        if a.get("name") == BIN_ASSET:
            return a["browser_download_url"], a["name"]
    for a in assets:
        n = str(a.get("name", "")).lower()
        if re.fullmatch(r"whisper.*bin.*x64.*\.zip", n) and "cublas" not in n and "cuda" not in n:
            return a["browser_download_url"], a["name"]
    raise RuntimeError(f"Im neuesten whisper.cpp-Release gibt es keine Datei '{BIN_ASSET}'. "
                       "Bitte lade whisper.cpp manuell herunter (siehe README).")


def download_program(url: str | None = None, progress=None, cancelled=None, api_url: str = RELEASE_API,
                     min_bytes: int = 100_000) -> Path:
    import tempfile
    if url is None:
        url, _ = find_program_asset(api_url)
    tmp = Path(tempfile.mkdtemp(prefix="clipforge_wcpp_")) / "whisper.zip"
    try:
        download_file(url, tmp, progress, cancelled, min_bytes)
        safe_extract(tmp, subtitles.whisper_dir())
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    if subtitles.find_whisper_program() is None:
        raise RuntimeError("Nach dem Entpacken wurde kein whisper-cli gefunden.")
    return subtitles.whisper_dir()


def setup_all(model: str = "base", progress=None, cancelled=None, **kw) -> None:
    """Lädt fehlende Teile (Programm und/oder Modell). progress(Text, Anteil 0–1)."""
    p = progress or (lambda t, f: None)
    if subtitles.find_whisper_program() is None:
        download_program(kw.get("program_url"), lambda f: p("Programm wird geladen …", f * 0.2), cancelled,
                         kw.get("api_url", RELEASE_API), kw.get("min_bytes", 100_000))
    if subtitles.find_whisper_model() is None:
        download_model(model, kw.get("model_url"), lambda f: p("Sprachmodell wird geladen …", 0.2 + f * 0.8), cancelled,
                       kw.get("model_min_bytes"))
    p("Fertig", 1.0)
