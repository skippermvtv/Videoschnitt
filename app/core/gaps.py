"""Lücken schließen und Ripple-Löschen.

Die Hauptspur (V1) ist immer lückenlos: löscht man einen Clip, rücken die folgenden nach. Bild-in-Bild, freie Audioblöcke und
Effekt-Blöcke liegen dagegen auf festen Zeiten. Beim Ripple-Löschen wandern sie deshalb mit, damit sie am passenden Bild
bleiben. "Alle Lücken schließen" entfernt leere Stellen auf diesen Spuren.
"""
from __future__ import annotations

from .project import Project

EPS = 0.001


def _shift_after(project: Project, t0: float, t1: float, d: float) -> int:
    """Nach dem Entfernen der Zeitspanne [t0, t1) (Länge d): Blöcke dahinter rücken um d nach vorn, Blöcke komplett darin
    werden gelöscht, Blöcke, die in die Spanne hineinragen, beginnen am Schnittpunkt. Gibt die Zahl gelöschter Blöcke zurück."""
    removed = 0
    # Effekte: rohe Zeiten verwenden (fx_span würde das Ende schon auf die neue, kürzere Projektlänge kappen)
    for i in range(len(project.effects) - 1, -1, -1):
        e = project.effects[i]
        s = max(0.0, float(e.get("start") or 0.0))
        en = e.get("end")
        en = None if en is None else float(en)
        if en is None and s <= EPS:
            continue                              # gilt fürs ganze Projekt
        if en is not None and s >= t0 - EPS and en <= t1 + EPS:
            del project.effects[i]
            removed += 1
            continue
        if en is not None and en <= t0 + EPS:
            continue                              # liegt komplett davor
        ns = s - d if s >= t1 - EPS else min(s, t0)
        ne = None if en is None else (en - d if en >= t1 - EPS else t0)
        ns = max(0.0, ns)
        project.fx_set_span(i, ns, project.duration if ne is None else max(ne, ns + project.FX_MIN))
    for i in range(len(project.overlays) - 1, -1, -1):
        o = project.overlays[i]
        s, en = o.start, o.start + o.length
        if s >= t0 - EPS and en <= t1 + EPS:
            del project.overlays[i]
            removed += 1
        elif s >= t1 - EPS:
            o.start = round(max(0.0, s - d), 3)
        elif en > t0 + EPS:                       # ragt in die Spanne: Anfang bleibt, Ende wird vom Projektende begrenzt
            pass
    for i in range(len(project.audio_clips) - 1, -1, -1):
        a = project.audio_clips[i]
        if a.kind == "video":
            continue                              # gebundene Töne folgen ihrem Clip (sync_linked)
        s, en = a.start, a.start + a.length
        if s >= t0 - EPS and en <= t1 + EPS:
            del project.audio_clips[i]
            removed += 1
        elif s >= t1 - EPS:
            a.start = round(max(0.0, s - d), 3)
    return removed


def ripple_delete(project: Project, clip_indexes, shift_tracks: bool = True) -> dict:
    """Löscht Clips der Hauptspur und rückt alles Spätere auf den anderen Spuren nach.
    Mit shift_tracks=False werden nur die Clips gelöscht (die anderen Spuren bleiben auf ihren Zeiten).
    Gibt {"clips": n, "removed": m, "seconds": d} zurück (m = zusätzlich entfernte Blöcke, die ganz im gelöschten Stück lagen)."""
    idx = sorted({i for i in clip_indexes if isinstance(i, int) and 0 <= i < len(project.clips)}, reverse=True)
    if not idx:
        return {"clips": 0, "removed": 0, "seconds": 0.0}
    total_d = 0.0
    removed = 0
    for i in idx:
        t0 = project.clip_start(i)
        before = project.duration
        project.reattach_audio(i)
        del project.clips[i]
        project.sync_linked()
        d = max(0.0, before - project.duration)
        if d > EPS and shift_tracks:
            removed += _shift_after(project, t0, t0 + d, d)
            total_d += d
    return {"clips": len(idx), "removed": removed, "seconds": round(total_d, 3)}


def _chains(project: Project):
    """Gruppen verschiebbarer Blöcke: je Spur ein Eintrag (Art, Nummer, Anfang, Ende)."""
    groups: dict = {}
    for i, o in enumerate(project.overlays):
        groups.setdefault("o", []).append(("o", i, o.start, o.start + o.length))
    for i, a in enumerate(project.audio_clips):
        if a.kind != "video":
            groups.setdefault(("a", a.track), []).append(("a", i, a.start, a.start + a.length))
    for i in range(len(project.effects)):
        e = project.effects[i]
        if e.get("end") is None and not e.get("start"):
            continue
        s, en = project.fx_span(i)
        groups.setdefault("f", []).append(("f", i, s, en))
    return groups


def count_gaps(project: Project) -> int:
    """Wie viele Lücken zwischen Blöcken gleicher Spur es gibt."""
    n = 0
    for items in _chains(project).values():
        end = None
        for _k, _i, s, e in sorted(items, key=lambda x: (x[2], x[3])):
            if end is not None and s > end + 0.01:
                n += 1
            end = e if end is None else max(end, e)
    return n


def close_all(project: Project) -> dict:
    """Schließt alle Lücken zwischen Blöcken derselben Spur (Bild-in-Bild, je Audiospur, Effekte). Der erste Block jeder Spur
    bleibt stehen, Überlappungen bleiben erhalten. Gibt {"gaps": n, "moved": m} zurück."""
    gaps = moved = 0
    for items in _chains(project).values():
        end = None          # Ende der bisherigen zusammenhängenden Gruppe (Originalzeit)
        shift = 0.0         # Verschiebung der aktuellen Gruppe
        for k, i, s, e in sorted(items, key=lambda x: (x[2], x[3])):
            if end is None:
                end = e
            elif s <= end + 0.01:                       # überlappt die Gruppe: gleiche Verschiebung, Überlappung bleibt
                end = max(end, e)
            else:                                       # Lücke: neue Gruppe rückt direkt an die vorige heran
                shift = s - (end - shift)
                end = e
                gaps += 1
            if shift > 0.0005:
                moved += 1
                if k == "o":
                    project.overlays[i].start = round(s - shift, 3)
                elif k == "a":
                    project.audio_clips[i].start = round(s - shift, 3)
                else:
                    project.fx_set_span(i, s - shift, e - shift)
    return {"gaps": gaps, "moved": moved}
