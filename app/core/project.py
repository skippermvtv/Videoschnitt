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


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
IMAGE_DEFAULT = 5.0          # Standardlänge eines Standbilds auf der Timeline (Sekunden)
IMAGE_MAX = 3600.0           # so lange darf ein Standbild maximal gezeigt werden


def is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


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
    if is_image_path(path):
        info.is_image = True
        info.duration = IMAGE_DEFAULT
        info.has_audio = False
    return info


def probe_audio(path: str) -> float:
    """Länge einer Audiodatei (oder eines Videos mit Ton) in Sekunden; wirft ValueError ohne Ton."""
    import json as _json
    r = _run([find_binary("ffprobe"), "-v", "error", "-show_streams", "-show_format",
              "-of", "json", path])
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or "Datei konnte nicht gelesen werden")
    data = _json.loads(r.stdout or "{}")
    if not any(s.get("codec_type") == "audio" for s in data.get("streams", [])):
        raise ValueError("Die Datei enthält keinen Ton.")
    try:
        d = float(data.get("format", {}).get("duration", 0) or 0)
    except ValueError:
        d = 0.0
    if d <= 0:
        raise ValueError("Die Länge der Audiodatei ist unbekannt.")
    return d


TRACK_NAMES = {1: "A1 Ton", 2: "A2 Musik", 3: "A3 frei"}


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex[:10]


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
    grade: dict = field(default_factory=dict)   # Bildkorrektur (siehe core/grade.py)
    audio_detached: bool = False                # Ton liegt als eigener Audioclip auf A1
    uid: str = field(default_factory=_uid)
    transition: str = ""          # Übergang ZUM NÄCHSTEN Clip (id aus presets/transitions.json), leer = harter Schnitt
    transition_dur: float = 0.8
    is_image: bool = False         # Standbild: Länge frei wählbar, kein Ton
    rotate: int = 0                # 0 | 90 | 180 | 270 (im Uhrzeigersinn)
    flip_h: bool = False
    flip_v: bool = False
    crop_l: float = 0.0            # Zuschneiden in % der Breite/Höhe
    crop_r: float = 0.0
    crop_t: float = 0.0
    crop_b: float = 0.0
    keyframes: list = field(default_factory=list)   # Bewegung: [{"t":0..1,"zoom":100..400,"x":-100..100,"y":..,"rot":°}]
    motion_ease: bool = True       # sanfte Übergänge zwischen den Keyframes
    stabilize: int = 0             # Videostabilisierung 0 (aus) … 100 (stark), siehe core/stabilize.py

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

    @property
    def has_transform(self) -> bool:
        return bool(self.rotate % 360 or self.flip_h or self.flip_v or self.crop_l or self.crop_r
                    or self.crop_t or self.crop_b)


def overlap(clip: "Clip", len_this: float, len_next: float | None) -> float:
    """Sekunden, um die sich dieser Clip mit dem nächsten überlappt (Übergang); 0 = harter Schnitt."""
    if not clip.transition or len_next is None:
        return 0.0
    return max(0.0, min(clip.transition_dur, len_this / 2.0 - 0.02, len_next / 2.0 - 0.02))


@dataclass
class AudioClip:
    """Eigener Audioblock auf der Timeline (Spur 1 = Ton, 2 = Musik, 3 = frei)."""
    path: str
    duration: float            # Länge der Quelldatei
    in_pt: float = 0.0
    out_pt: float = 0.0        # 0 → bis zum Ende
    start: float = 0.0         # Startzeit auf der Timeline (Sekunden)
    track: int = 2
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    speed: float = 1.0
    mute: bool = False
    loop: bool = False         # wiederholen, bis das Video endet
    reverse: bool = False
    kind: str = "file"         # "file" (importiert) | "video" (vom Clip getrennt)
    link: str = ""             # uid des Videoclips bei kind="video"
    link_offset: float = 0.0   # Abstand zum Anfang des verknüpften Clips
    name: str = ""

    def __post_init__(self):
        if not self.out_pt:
            self.out_pt = self.duration
        if not self.name:
            self.name = Path(self.path).name

    @property
    def length(self) -> float:
        """Länge auf der Timeline (nach Geschwindigkeit, ohne Loop)."""
        return max(0.05, (self.out_pt - self.in_pt) / max(self.speed, 0.01))


@dataclass
class OverlayClip:
    """Bild-in-Bild: Video oder Standbild, das über dem Hauptvideo (V2) eingeblendet wird."""
    path: str
    duration: float            # Länge der Quelle (bei Bildern IMAGE_MAX)
    in_pt: float = 0.0
    out_pt: float = 0.0
    start: float = 0.0         # Startzeit auf der Timeline
    speed: float = 1.0
    is_image: bool = False
    x_pct: float = 75.0        # Mitte des Overlays in % der Bildbreite
    y_pct: float = 25.0        # … und der Bildhöhe
    size_pct: float = 35.0     # Breite in % der Bildbreite
    opacity: float = 100.0     # 0 … 100
    fade_in: float = 0.0
    fade_out: float = 0.0
    border: bool = False
    name: str = ""
    key_color: str = ""        # Chroma-Key (Greenscreen): "" = aus, sonst "#RRGGBB"
    key_similarity: float = 30.0   # Toleranz 0 … 100
    key_blend: float = 20.0        # weiche Kante 0 … 100
    key_spill: bool = True         # Farbsaum der Schlüsselfarbe entfernen

    def __post_init__(self):
        if not self.out_pt:
            self.out_pt = self.duration
        if not self.name:
            self.name = Path(self.path).name

    @property
    def length(self) -> float:
        return max(0.05, (self.out_pt - self.in_pt) / max(self.speed, 0.01))


OVERLAY_CORNERS = {"tr": (78.0, 22.0), "tl": (22.0, 22.0), "br": (78.0, 78.0), "bl": (22.0, 78.0), "c": (50.0, 50.0)}


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
    anim: str = "none"         # none | fade | slide_up | slide_left | bounce | typewriter | shake | blink
    anim_dur: float = 0.4      # Dauer des Ein-/Ausblendens bzw. Tippens (Sekunden)
    box: bool = False          # halbtransparenter Kasten hinter dem Text


TEXT_ANIMS = [("none", "Keine"), ("fade", "Einblenden / Ausblenden"), ("slide_up", "Von unten hereinfahren"),
              ("slide_left", "Von rechts hereinfahren"), ("bounce", "Hüpfen"), ("typewriter", "Schreibmaschine"),
              ("shake", "Wackeln"), ("blink", "Blinken")]


@dataclass
class SubtitleCue:
    start: float = 0.0
    end: float = 2.0
    text: str = ""


@dataclass
class SubtitleStyle:
    font: str = ""
    size_pct: float = 5.5
    color: str = "#ffffff"
    border_color: str = "black"
    position: str = "bottom"
    box: bool = False
    anim: str = "none"
    anim_dur: float = 0.2


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
    audio_clips: list[AudioClip] = field(default_factory=list)
    overlays: list[OverlayClip] = field(default_factory=list)
    subtitles: list[SubtitleCue] = field(default_factory=list)
    sub_style: SubtitleStyle = field(default_factory=SubtitleStyle)
    track_volume: dict = field(default_factory=dict)   # {"1": 1.0, "2": 0.8, ...}
    track_mute: dict = field(default_factory=dict)     # {"2": True}
    ducking: bool = False          # Musik leiser, solange Ton (Video/A1) spricht
    ducking_amount: float = 0.6    # 0 … 1
    normalize: bool = False        # Lautheit auf -14 LUFS (YouTube/TikTok-Niveau)

    def overlap_after(self, i: int) -> float:
        nxt = self.clips[i + 1].length if i + 1 < len(self.clips) else None
        return overlap(self.clips[i], self.clips[i].length, nxt)

    @property
    def duration(self) -> float:
        return sum(c.length for c in self.clips) - sum(self.overlap_after(i) for i in range(len(self.clips)))

    def clip_start(self, index: int) -> float:
        return sum(c.length for c in self.clips[:index]) - sum(self.overlap_after(i) for i in range(index))

    # --- Effekt-Spur (FX): jeder Eintrag in `effects` ist ein Block {"id", "intensity", "start", "end"} ----------
    FX_MIN = 0.1          # kürzester Block in Sekunden

    def fx_span(self, i: int) -> tuple[float, float]:
        """(Anfang, Ende) des Effekt-Blocks in Sekunden. Ohne Angaben gilt der Effekt für das ganze Projekt."""
        e = self.effects[i]
        total = max(self.duration, 0.0)
        s = max(0.0, float(e.get("start") or 0.0))
        t = e.get("end")
        t = total if t is None else float(t)
        if total > 0:
            t = min(t, total)
        return s, max(t, s + self.FX_MIN)

    def fx_set_span(self, i: int, start: float, end: float) -> None:
        """Setzt Anfang/Ende. Reicht ein Block vom Anfang bis zum Ende des Projekts, werden keine Zeiten gespeichert."""
        e = self.effects[i]
        total = self.duration
        start = max(0.0, float(start))
        end = max(float(end), start + self.FX_MIN)
        if total > 0:
            end = min(end, max(total, start + self.FX_MIN))
        whole_end = total > 0 and end >= total - 0.01
        if start <= 0.005 and (whole_end or total <= 0):
            e.pop("start", None)
            e.pop("end", None)
            return
        e["start"] = round(start, 3)
        e["end"] = None if whole_end else round(end, 3)

    def fx_add(self, effect_id: str, intensity: float, at: float = 0.0, length: float | None = None) -> int:
        """Legt einen neuen Effekt-Block an und gibt seinen Index zurück."""
        self.effects.append({"id": effect_id, "intensity": intensity})
        i = len(self.effects) - 1
        total = self.duration
        if length is None:
            length = 3.0
        at = max(0.0, at)
        if total > 0:
            at = min(at, max(0.0, total - self.FX_MIN))
            length = min(length, total - at)
        self.fx_set_span(i, at, at + max(length, self.FX_MIN))
        return i

    def fx_rows(self, max_rows: int = 3) -> list[int]:
        """Zeile (0, 1, 2 …) für jeden Block, damit sich überlappende Effekte nicht verdecken."""
        order = sorted(range(len(self.effects)), key=lambda i: (self.fx_span(i)[0], i))
        row_end: list[float] = []
        rows = [0] * len(self.effects)
        for i in order:
            s, t = self.fx_span(i)
            for r, end in enumerate(row_end):
                if s >= end - 1e-6:
                    row_end[r] = t
                    rows[i] = r
                    break
            else:
                if len(row_end) < max_rows:
                    row_end.append(t)
                    rows[i] = len(row_end) - 1
                else:
                    rows[i] = max_rows - 1
        return rows

    def clip_index(self, uid: str) -> int:
        for i, c in enumerate(self.clips):
            if c.uid == uid:
                return i
        return -1

    # --- Ton vom Video trennen / wieder verbinden ------------------------------------
    def detach_audio(self, index: int) -> AudioClip | None:
        """Legt den Ton des Clips als eigenen Block auf A1 und stummt den Ton im Video."""
        c = self.clips[index]
        if c.audio_detached or not c.has_audio:
            return None
        a = AudioClip(path=c.path, duration=c.duration, in_pt=c.in_pt, out_pt=c.out_pt,
                      start=self.clip_start(index), track=1, volume=0.0 if c.mute else c.volume,
                      speed=c.speed, mute=c.mute, reverse=c.reverse, kind="video", link=c.uid,
                      link_offset=0.0, name=f"Ton: {c.name}")
        c.audio_detached = True
        self.audio_clips.append(a)
        return a

    def reattach_audio(self, index: int) -> bool:
        c = self.clips[index]
        before = len(self.audio_clips)
        self.audio_clips = [a for a in self.audio_clips if not (a.kind == "video" and a.link == c.uid)]
        c.audio_detached = False
        return len(self.audio_clips) != before

    def sync_linked(self) -> None:
        """Getrennte Töne folgen ihrem Clip (nach Verschieben/Löschen/Schneiden)."""
        keep = []
        for a in self.audio_clips:
            if a.kind == "video":
                i = self.clip_index(a.link)
                if i < 0:
                    continue
                a.start = self.clip_start(i) + a.link_offset
            keep.append(a)
        self.audio_clips = keep

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def save(self, path: str) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_json(cls, text: str) -> "Project":
        d = json.loads(text)
        p = cls(**{k: v for k, v in d.items() if k in (
            "format_id", "export_id", "layout", "look_id", "effects", "fade_in", "fade_out",
            "track_volume", "track_mute", "ducking", "ducking_amount", "normalize")})
        clip_fields = set(Clip.__dataclass_fields__)
        audio_fields = set(AudioClip.__dataclass_fields__)
        text_fields = set(TextLayer.__dataclass_fields__)
        ov_fields = set(OverlayClip.__dataclass_fields__)
        cue_fields = set(SubtitleCue.__dataclass_fields__)
        st_fields = set(SubtitleStyle.__dataclass_fields__)
        p.subtitles = [SubtitleCue(**{k: v for k, v in c.items() if k in cue_fields}) for c in d.get("subtitles", [])]
        if isinstance(d.get("sub_style"), dict):
            p.sub_style = SubtitleStyle(**{k: v for k, v in d["sub_style"].items() if k in st_fields})
        p.overlays = [OverlayClip(**{k: v for k, v in o.items() if k in ov_fields}) for o in d.get("overlays", [])]
        p.clips = [Clip(**{k: v for k, v in c.items() if k in clip_fields}) for c in d.get("clips", [])]
        p.audio_clips = [AudioClip(**{k: v for k, v in a.items() if k in audio_fields})
                         for a in d.get("audio_clips", [])]
        p.texts = [TextLayer(**{k: v for k, v in t.items() if k in text_fields}) for t in d.get("texts", [])]
        return p

    @classmethod
    def load(cls, path: str) -> "Project":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    # --- fehlende Dateien wiederfinden ------------------------------------------------
    def missing_paths(self) -> list[str]:
        import os
        seen: list[str] = []
        luts = [c.grade["lut"] for c in self.clips if isinstance(c.grade.get("lut"), str) and c.grade.get("lut")]
        for p in ([c.path for c in self.clips] + [a.path for a in self.audio_clips]
                  + [o.path for o in self.overlays] + luts):
            if not os.path.exists(p) and p not in seen:
                seen.append(p)
        return seen

    def relink(self, folder: str) -> tuple[int, list[str]]:
        """Sucht fehlende Dateien (nach Dateiname) in einem Ordner samt Unterordnern.

        Gibt (Anzahl gefundener Dateien, noch fehlende Pfade) zurück.
        """
        import os
        missing = self.missing_paths()
        if not missing:
            return 0, []
        wanted = {Path(m).name.lower(): m for m in missing}
        found: dict[str, str] = {}
        for root, _dirs, files in os.walk(folder):
            for f in files:
                key = f.lower()
                if key in wanted and wanted[key] not in found:
                    found[wanted[key]] = os.path.join(root, f)
            if len(found) == len(wanted):
                break
        for c in self.clips:
            if c.path in found:
                c.path = found[c.path]
            if c.grade.get("lut") in found:
                c.grade["lut"] = found[c.grade["lut"]]
        for a in self.audio_clips + self.overlays:
            if a.path in found:
                a.path = found[a.path]
        return len(found), [m for m in missing if m not in found]
