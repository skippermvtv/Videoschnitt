"""Mehrfachauswahl: gemeinsam löschen, duplizieren und verschieben.

Ein Eintrag der Auswahl ist ``(Art, Nummer)`` mit Art ``"v"`` (Clip der Hauptspur), ``"a"`` (Audioblock), ``"o"`` (Bild-in-Bild)
oder ``"f"`` (Effekt-Block).
"""
from __future__ import annotations

from . import duplicate
from .project import Project

KINDS = ("v", "a", "o", "f")


def clean(project: Project, items) -> list[tuple[str, int]]:
    """Nur gültige, einmalige Einträge (in fester Reihenfolge: Clips, Audio, Bild-in-Bild, Effekte; je Art aufsteigend)."""
    sizes = {"v": len(project.clips), "a": len(project.audio_clips), "o": len(project.overlays), "f": len(project.effects)}
    seen = set()
    for k, i in items or []:
        if k in sizes and isinstance(i, int) and 0 <= i < sizes[k]:
            seen.add((k, i))
    return [(k, i) for k in KINDS for i in sorted(i for kk, i in seen if kk == k)]


def counts(project: Project) -> tuple[int, int, int, int]:
    return len(project.clips), len(project.audio_clips), len(project.overlays), len(project.effects)


def delete(project: Project, items) -> int:
    """Löscht alle Einträge; gibt die Anzahl gelöschter Blöcke zurück. Ein getrennter Clip-Ton wird mit dem Clip entfernt."""
    items = clean(project, items)
    n = 0
    for _k, i in reversed([x for x in items if x[0] == "f"]):
        del project.effects[i]
        n += 1
    for _k, i in reversed([x for x in items if x[0] == "o"]):
        del project.overlays[i]
        n += 1
    for _k, i in reversed([x for x in items if x[0] == "a"]):
        del project.audio_clips[i]
        n += 1
    for _k, i in reversed([x for x in items if x[0] == "v"]):
        project.reattach_audio(i)
        del project.clips[i]
        n += 1
    project.sync_linked()
    return n


def duplicate_items(project: Project, items) -> list[tuple[str, int]]:
    """Kopiert jeden Eintrag direkt hinter das Original; gibt die Auswahl der Kopien zurück."""
    items = clean(project, items)
    new: list[tuple[str, int]] = []
    for kind, fn in (("f", lambda i: duplicate.effect(project, i)[0]), ("o", lambda i: duplicate.overlay(project, i)),
                     ("a", lambda i: duplicate.audio(project, i)), ("v", lambda i: duplicate.clip(project, i))):
        for i in reversed([x[1] for x in items if x[0] == kind]):
            fn(i)
        idx = [x[1] for x in items if x[0] == kind]
        new += [(kind, i + k + 1) for k, i in enumerate(idx)]
    return new


def movable(project: Project, items) -> dict[tuple[str, int], tuple[float, float]]:
    """Welche Einträge sich mit der Maus verschieben lassen und ihre (Anfang, Ende): Bild-in-Bild, freie Audioblöcke und Effekt-Blöcke.
    Clips der Hauptspur und an Clips gebundene Töne folgen der Reihenfolge der Hauptspur und werden nicht einzeln verschoben."""
    out: dict[tuple[str, int], tuple[float, float]] = {}
    for k, i in clean(project, items):
        if k == "o":
            o = project.overlays[i]
            out[(k, i)] = (o.start, o.start + o.length)
        elif k == "a" and project.audio_clips[i].kind != "video":
            a = project.audio_clips[i]
            out[(k, i)] = (a.start, a.start + a.length)
        elif k == "f":
            out[(k, i)] = project.fx_span(i)
    return out


def move(project: Project, orig: dict[tuple[str, int], tuple[float, float]], dt: float) -> float:
    """Verschiebt alle Einträge aus `orig` (Zustand vor dem Ziehen) um dt Sekunden; keiner wird vor 0 geschoben und kein
    Effekt-Block über das Projektende hinaus. Gibt die tatsächlich angewendete Verschiebung zurück."""
    if not orig:
        return 0.0
    dt = max(dt, -min(s for s, _e in orig.values()))
    total = project.duration
    fx_ends = [e for (k, _i), (_s, e) in orig.items() if k == "f"]
    if fx_ends and total > 0:
        dt = min(dt, max(0.0, total - max(fx_ends)))
    for (k, i), (s, e) in orig.items():
        if k == "o":
            project.overlays[i].start = round(s + dt, 3)
        elif k == "a":
            project.audio_clips[i].start = round(s + dt, 3)
        elif k == "f":
            project.fx_set_span(i, s + dt, e + dt)
    return dt
