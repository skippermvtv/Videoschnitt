"""Update-Check über GitHub Releases.

Ablauf: Beim Start (oder per Menü "Nach Updates suchen") wird das neueste Release
des Repositories abgefragt. Ist die Versionsnummer höher, wird die Setup-Datei
heruntergeladen und gestartet; sie ersetzt die alte Version.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..version import APP_NAME, GITHUB_REPO, VERSION

_API = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass
class UpdateInfo:
    version: str
    notes: str
    asset_url: str
    asset_name: str
    page_url: str


def _parse(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v)
    return tuple(int(x) for x in nums[:4]) or (0,)


def is_newer(remote: str, local: str = VERSION) -> bool:
    return _parse(remote) > _parse(local)


def configured() -> bool:
    return bool(GITHUB_REPO) and not GITHUB_REPO.startswith("DEIN-")


def check(timeout: float = 8.0) -> UpdateInfo | None:
    """Gibt UpdateInfo zurück, wenn eine neuere Version existiert, sonst None.

    Wirft Exception bei Netzwerkproblemen (der Aufrufer entscheidet, ob er das zeigt).
    """
    if not configured():
        raise RuntimeError("GITHUB_REPO ist in app/version.py noch nicht eingetragen.")
    req = urllib.request.Request(
        _API.format(repo=GITHUB_REPO),
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"{APP_NAME}/{VERSION}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = str(data.get("tag_name", ""))
    if not tag or not is_newer(tag):
        return None
    asset = next((a for a in data.get("assets", []) if str(a.get("name", "")).lower().endswith("setup.exe")), None)
    if not asset:
        return None
    return UpdateInfo(
        version=tag.lstrip("vV"),
        notes=str(data.get("body") or "")[:1500],
        asset_url=asset["browser_download_url"],
        asset_name=asset["name"],
        page_url=str(data.get("html_url", "")),
    )


def download(info: UpdateInfo, on_progress: Callable[[float], None] | None = None) -> Path:
    target = Path(tempfile.mkdtemp(prefix="clipforge_update_")) / info.asset_name
    req = urllib.request.Request(info.asset_url, headers={"User-Agent": f"{APP_NAME}/{VERSION}"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(target, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if on_progress and total:
                on_progress(done / total)
    return target


def launch_installer(path: Path) -> None:
    """Startet die Setup.exe (Windows). Das Programm sollte danach beendet werden."""
    if os.name != "nt":
        raise RuntimeError("Automatisches Installieren geht nur unter Windows.")
    subprocess.Popen([str(path), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                     close_fds=True)
