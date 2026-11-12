"""Einen Clip in Stücke teilen (Stille entfernen, Szenenerkennung): gemeinsame Logik. Ohne Qt."""
from __future__ import annotations

import copy
import uuid

from .project import Clip, Project

MAX_PIECES = 400


class PieceError(Exception):
    pass


def split_into(project: Project, idx: int, ranges: list[tuple[float, float]]) -> list[int]:
    """Ersetzt den Clip `idx` durch Stücke mit den Quell-Bereichen `ranges` (in Quell-Sekunden, aufsteigend).
    Gibt die Indizes der neuen Stücke zurück. Der Übergang zum nächsten Clip bleibt am letzten Stück,
    Keyframes werden auf die Stücke verteilt, ein getrennter Ton wird vorher wieder verbunden."""
    from .window import _remap_keys
    if not 0 <= idx < len(project.clips):
        raise PieceError("Kein Clip gewählt.")
    c = project.clips[idx]
    if c.is_image:
        raise PieceError("Bei einem Standbild geht das nicht.")
    if c.ramp_id:
        raise PieceError("Der Clip gehört zu einer Tempokurve. Erst „Kurve entfernen“, dann erneut versuchen.")
    if c.reverse:
        raise PieceError("Bei einem rückwärts laufenden Clip geht das nicht. Erst „Rückwärts“ ausschalten.")
    if not ranges:
        raise PieceError("Es bliebe nichts übrig.")
    if len(ranges) > MAX_PIECES:
        raise PieceError(f"Das wären {len(ranges)} Stücke (höchstens {MAX_PIECES}). Die Einstellung weniger empfindlich wählen.")
    if c.audio_detached:
        project.reattach_audio(idx)
    seg = c.out_pt - c.in_pt
    base_in, last_trans, last_dur = c.in_pt, c.transition, c.transition_dur
    keys, ease = list(c.keyframes or []), c.motion_ease
    new: list[Clip] = []
    for k, (a, b) in enumerate(ranges):
        piece = c if k == 0 else copy.deepcopy(c)
        if k > 0:
            piece.uid = uuid.uuid4().hex[:10]
        piece.in_pt, piece.out_pt = a, b
        piece.transition, piece.transition_dur = ("", c.transition_dur) if k < len(ranges) - 1 else (last_trans, last_dur)
        if keys:
            piece.keyframes, piece.motion_ease = _remap_keys(keys, ease, 1.0, (a - base_in) / seg, (b - base_in) / seg)
        new.append(piece)
    project.clips[idx:idx + 1] = new
    project.sync_linked()
    return list(range(idx, idx + len(new)))
