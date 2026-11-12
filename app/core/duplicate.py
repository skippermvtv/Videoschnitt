"""Duplizieren (Strg+D): Clip, Bild-in-Bild, Audioblock oder Effekt-Block als Kopie direkt dahinter."""
from __future__ import annotations

import copy
import uuid

from .project import Project


class DuplicateError(Exception):
    pass


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def clip(project: Project, idx: int) -> int:
    """Kopie des Clips direkt hinter dem Original. Ein getrennter Ton wird mitkopiert. Gibt den Index der Kopie zurück.
    Der Übergang zum nächsten Clip wandert an die Kopie; zwischen Original und Kopie ist ein harter Schnitt.
    Eine Tempokurve wird nicht mitkopiert (die Kopie ist ein normaler Clip mit dem Tempo des gewählten Stücks)."""
    if not 0 <= idx < len(project.clips):
        raise DuplicateError("Zuerst einen Clip in der Timeline anklicken.")
    src = project.clips[idx]
    new = copy.deepcopy(src)
    new.uid = _uid()
    new.ramp_id, new.ramp_pts, new.ramp_keys = "", [], []
    new.ramp_speed, new.ramp_ease = 1.0, True
    src.transition = ""
    project.clips.insert(idx + 1, new)
    for a in [a for a in project.audio_clips if a.kind == "video" and a.link == src.uid]:
        b = copy.deepcopy(a)
        b.link = new.uid
        project.audio_clips.append(b)
    project.sync_linked()
    return idx + 1


def overlay(project: Project, idx: int) -> int:
    if not 0 <= idx < len(project.overlays):
        raise DuplicateError("Zuerst ein Bild-in-Bild in der Timeline anklicken.")
    o = project.overlays[idx]
    new = copy.deepcopy(o)
    new.start = o.start + o.length
    project.overlays.insert(idx + 1, new)
    return idx + 1


def audio(project: Project, idx: int) -> int:
    """Kopie des Audioblocks direkt dahinter (auf derselben Spur). Die Kopie ist ein freier Block, nicht an einen Clip gebunden."""
    if not 0 <= idx < len(project.audio_clips):
        raise DuplicateError("Zuerst einen Audioblock in der Timeline anklicken.")
    a = project.audio_clips[idx]
    new = copy.deepcopy(a)
    new.kind, new.link, new.link_offset = "file", "", 0.0
    new.start = a.start + a.length
    project.audio_clips.insert(idx + 1, new)
    return idx + 1


def effect(project: Project, idx: int) -> tuple[int, bool]:
    """Kopie des Effekt-Blocks direkt dahinter. Gibt (Index, passt_dahinter) zurück: reicht der Block bis zum Ende des Projekts,
    wird die Kopie an das Ende gelegt und überlagert das Original (False)."""
    if not 0 <= idx < len(project.effects):
        raise DuplicateError("Zuerst einen Effekt-Block in der Timeline anklicken.")
    s, e = project.fx_span(idx)
    total = project.duration
    length = e - s
    new = copy.deepcopy(project.effects[idx])
    project.effects.insert(idx + 1, new)
    fits = total <= 0 or e + project.FX_MIN <= total + 1e-6
    if fits:
        project.fx_set_span(idx + 1, e, min(e + length, total) if total > 0 else e + length)
    else:
        project.fx_set_span(idx + 1, max(0.0, total - length), total)
    return idx + 1, fits
