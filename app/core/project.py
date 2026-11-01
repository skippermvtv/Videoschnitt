"""Datenmodell des Projekts (wird als .cforge-JSON gespeichert)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..paths import find_binary

_NOWINDOW = 0x08000000  # CREATE_NO_WINDOW (Windows)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    import os
    flags = _NOWINDOW if os.name == "nt" else 0
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=flags)


@dataclass
class MediaInfo:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = False
    is_image: bool = False


def probe(path: str) -> MediaInfo:
    import json as _json
    r = _run([find_binary("ffprobe"), "-v", "error", "-show_streams", "-show_format",
              "-of", "json", path])
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or "Datei konnte nicht gelesen werden")
    data = _json.loads(r.stdout or "{}")
    info = MediaInfo()
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.width:
            info.width, info.height = int(s.get("width", 0)), int(s.get("height", 0))
            # Drehung (Handy-Videos) berücksichtigen
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rot = int(float(sd["rotation"]))
            if abs(rot) in (90, 270):
                info.width, info.height = info.height, info.width
        elif s.get("codec_type") == "audio":
            info.has_audio = True
    try:
        info.duration = float(data.get("format", {}).get("duration", 0) or 0)
    except ValueError:
        info.duration = 0.0
    if not info.width:
        raise ValueError("Die Datei enthält kein Video.")
    return info


@dataclass
class Clip:
    path: str
    duration: float            # Länge der Quelldatei
    in_pt: float = 0.0
    out_pt: float = 0.0        # 0 → bis zum Ende
    speed: float = 1.0
    volume: float = 1.0
    mute: bool = False
    reverse: bool = False
    has_audio: bool = True
    width: int = 0
    height: int = 0

    def __post_init__(self):
        if not self.out_pt:
            self.out_pt = self.duration

    @property
    def length(self) -> float:
        """Länge auf der Timeline (nach Geschwindigkeit)."""
        return max(0.05, (self.out_pt - self.in_pt) / max(self.speed, 0.01))

    @property
    def name(self) -> str:
        return Path(self.path).name


@dataclass
class TextLayer:
    text: str = "Dein Text"
    start: float = 0.0
    end: float = 3.0
    position: str = "bottom"   # top | center | bottom
    size_pct: float = 7.0      # Schriftgröße in % der Videohöhe
    color: str = "white"
    border_color: str = "black"
    font: str = ""             # Pfad zur Schriftdatei; leer → Standardschrift


@dataclass
class Project:
    format_id: str = "youtube_16_9"
    export_id: str = "youtube_1080p"
    layout: str = ""           # leer → vom Format-Preset
    look_id: str = "none"
    clips: list[Clip] = field(default_factory=list)
    effects: list[dict] = field(default_factory=list)
    texts: list[TextLayer] = field(default_factory=list)
    fade_in: float = 0.0
    fade_out: float = 0.0

    @property
    def duration(self) -> float:
        return sum(c.length for c in self.clips)

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "Project":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        p = cls(**{k: v for k, v in d.items() if k in ("format_id", "export_id", "layout",
                                                       "look_id", "effects", "fade_in", "fade_out")})
        p.clips = [Clip(**c) for c in d.get("clips", [])]
        p.texts = [TextLayer(**t) for t in d.get("texts", [])]
        return p
