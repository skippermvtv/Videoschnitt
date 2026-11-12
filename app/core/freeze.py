"""Standbild einfügen: das Bild unter dem Abspielkopf wird für einige Sekunden angehalten (Freeze-Frame).

Das Bild kommt aus der Quelldatei des Clips (ohne Effekte); Bildkorrektur, Drehen/Spiegeln, Zuschnitt und Chroma-Key des Clips
werden übernommen, damit das Standbild genauso aussieht wie das Video davor und danach.
"""
from __future__ import annotations

import copy
import uuid
from pathlib import Path

from .. import paths
from .project import IMAGE_MAX, Clip, Project

DEFAULT_SECONDS = 3.0
MIN_SECONDS = 0.5
MAX_SECONDS = 10.0
EDGE = 0.05            # näher als das am Clip-Rand: nicht teilen, sondern davor/dahinter einfügen


def clamp_seconds(sec: float) -> float:
    return max(MIN_SECONDS, min(MAX_SECONDS, float(sec)))


def frames_dir() -> Path:
    p = paths.user_dir() / "standbilder"
    p.mkdir(parents=True, exist_ok=True)
    return p


def locate(project: Project, t: float):
    """(Clip-Nummer, Zeit im Clip) zur Projektzeit t; None, wenn es keine Clips gibt oder der Clip selbst ein Standbild ist."""
    cl = project.clips
    if not cl:
        return None
    idx = len(cl) - 1
    for i in range(len(cl)):
        if t < project.clip_start(i) + cl[i].length:
            idx = i
            break
    c = cl[idx]
    if c.is_image:
        return None
    return idx, max(0.0, min(c.length, t - project.clip_start(idx)))


def source_time(clip: Clip, local: float) -> float:
    """Zeit in der Quelldatei zur Zeit `local` auf der Timeline (berücksichtigt Tempo und Rückwärts)."""
    s = clip.out_pt - local * clip.speed if clip.reverse else clip.in_pt + local * clip.speed
    return max(clip.in_pt, min(clip.out_pt - 0.04, s)) if clip.out_pt - clip.in_pt > 0.08 else clip.in_pt


def extract(clip: Clip, local: float, png: str) -> None:
    from . import frames
    frames.extract_frame(clip.path, png, source_time(clip, local))


def new_png_path() -> str:
    return str(frames_dir() / f"standbild_{uuid.uuid4().hex[:8]}.png")


def make_clip(src: Clip, png: str, seconds: float) -> Clip:
    """Bild-Clip mit den Bild-Einstellungen von `src`; Tempo, Ton, Bewegung und Stabilisierung entfallen."""
    c = copy.deepcopy(src)
    c.uid = uuid.uuid4().hex[:10]
    c.path = png
    c.is_image = True
    c.duration = IMAGE_MAX
    c.in_pt = 0.0
    c.out_pt = clamp_seconds(seconds)
    c.speed = 1.0
    c.volume = 1.0
    c.mute = False
    c.reverse = False
    c.has_audio = False
    c.audio_detached = False
    c.transition = ""
    c.keyframes = []
    c.stabilize = 0
    c.denoise = 0
    c.voice = 0
    c.ramp_id = ""
    c.ramp_pts = []
    c.ramp_speed = 1.0
    c.ramp_keys = []
    return c


def insert(project: Project, idx: int, local: float, png: str, seconds: float) -> int:
    """Fügt das Standbild bei `local` Sekunden im Clip `idx` ein (der Clip wird dort geteilt). Gibt die Nummer des Bild-Clips zurück.
    Alles dahinter rückt um die Länge des Standbilds nach hinten; Spuren darüber bleiben auf ihren Zeiten."""
    c = project.clips[idx]
    img = make_clip(c, png, seconds)
    if local <= EDGE:
        project.clips.insert(idx, img)
        n = idx
    elif local >= c.length - EDGE:
        img.transition = ""
        c_trans, c_dur = c.transition, c.transition_dur
        c.transition = ""
        img.transition, img.transition_dur = c_trans, c_dur      # der Übergang zum nächsten Clip gehört jetzt dem Standbild
        project.clips.insert(idx + 1, img)
        n = idx + 1
    else:
        if c.audio_detached:
            project.reattach_audio(idx)
        t = source_time(c, local)
        second = copy.deepcopy(c)
        second.uid = uuid.uuid4().hex[:10]
        if c.reverse:                      # rückwärts läuft zuerst der hintere Teil der Quelle (t … Ende)
            c.in_pt = t
            second.out_pt = t
        else:
            c.out_pt = t
            second.in_pt = t
        first, last = c, second
        first.transition = ""
        project.clips[idx:idx + 1] = [first, img, last]
        n = idx + 1
    project.sync_linked()
    return n
