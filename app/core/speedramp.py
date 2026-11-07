"""Geschwindigkeitskurve (Speed Ramp): das Tempo ändert sich weich innerhalb eines Clips.

Umsetzung: Der Clip wird in bis zu 20 aufeinanderfolgende Abschnitte geteilt, jeder mit gleichbleibender Geschwindigkeit.
Der Tempowert eines Abschnitts ist so gewählt, dass er genau so lange dauert wie die Kurve an dieser Stelle (Mittel über
den Abschnitt). Alle übrigen Teile des Programms (Timeline, Übergänge, Live-Vorschau, Export, Ton) sehen nur normale Clips.

Eine Kurve besteht aus Punkten (Position im Clip in %, Tempo als Faktor); dazwischen wird weich übergeblendet.
"""
from __future__ import annotations

import copy
import re
import uuid

from .project import Clip, Project

MIN_SPEED, MAX_SPEED = 0.1, 8.0          # Tempo der Kurve (Faktor)
CLIP_MIN, CLIP_MAX = 0.1, 20.0           # Grenzen eines Clips (Kurve × Grundtempo)
MAX_PIECES = 20
MIN_SEGMENT = 0.4                         # kürzere Clips (Quell-Sekunden) lassen sich nicht sinnvoll aufteilen

# (Kennung, Name, Punkte [Position %, Tempo ×])
PRESETS: list[tuple[str, str, list[list[float]]]] = [
    ("slow_mid", "Zeitlupe in der Mitte", [[0, 1], [30, 1], [50, 0.25], [70, 1], [100, 1]]),
    ("ramp_up", "Immer schneller", [[0, 0.5], [100, 4]]),
    ("ramp_down", "Abbremsen", [[0, 4], [100, 0.5]]),
    ("hero", "Heldenmoment (schnell – Zeitlupe – schnell)", [[0, 2], [35, 2], [50, 0.2], [65, 2], [100, 2]]),
    ("pulse", "Pulsieren", [[0, 1], [25, 3], [50, 0.4], [75, 3], [100, 1]]),
    ("flash_in", "Blitzstart", [[0, 6], [15, 1], [100, 1]]),
]


class SpeedRampError(Exception):
    pass


# ---------------------------------------------------------------- Kurve
def parse_points(text: str) -> list[list[float]]:
    """„0:1, 50:0.25, 100:1“ → [[0, 1], [50, 0.25], [100, 1]]  (Position in %, Tempo ×). Komma als Dezimalzeichen ist erlaubt,
    wenn Paare mit Semikolon oder Zeilenumbruch getrennt sind."""
    raw = [t for t in re.split(r"[;\n]+|,(?=\s*\d+(?:[.,]\d+)?\s*:)", text or "") if t.strip()]
    pts: list[list[float]] = []
    for part in raw:
        m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*%?\s*[:=]\s*[×xX]?\s*(\d+(?:[.,]\d+)?)\s*[×xX]?\s*,?\s*", part)
        if not m:
            raise SpeedRampError(f"Punkt nicht lesbar: „{part.strip()}“ (richtig: Position in %:Tempo, z. B. 50:0,25)")
        pts.append([float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))])
    return normalize(pts)


def normalize(points) -> list[list[float]]:
    """Prüft die Punkte, sortiert sie und ergänzt Anfang (0 %) und Ende (100 %), falls sie fehlen."""
    pts: list[list[float]] = []
    for p in points or []:
        try:
            pos, sp = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise SpeedRampError("Ungültiger Punkt in der Kurve.") from exc
        if not (pos == pos and sp == sp) or not 0.0 <= pos <= 100.0:
            raise SpeedRampError(f"Position {pos:g} % liegt nicht zwischen 0 und 100.")
        if not MIN_SPEED <= sp <= MAX_SPEED:
            raise SpeedRampError(f"Tempo ×{sp:g} liegt nicht zwischen ×{MIN_SPEED:g} und ×{MAX_SPEED:g}.")
        pts.append([pos, sp])
    if len(pts) < 2:
        raise SpeedRampError("Eine Kurve braucht mindestens zwei Punkte.")
    pts.sort(key=lambda q: q[0])
    for a, b in zip(pts, pts[1:]):
        if b[0] - a[0] < 1e-6:
            raise SpeedRampError(f"Zwei Punkte liegen bei {a[0]:g} % übereinander.")
    if pts[0][0] > 0.0:
        pts.insert(0, [0.0, pts[0][1]])
    if pts[-1][0] < 100.0:
        pts.append([100.0, pts[-1][1]])
    return pts


# ---------------------------------------------------------------- Eigene Kurven (in den Einstellungen gespeichert)
MAX_SAVED = 20
MAX_NAME = 40


def clean_saved(raw) -> list[dict]:
    """Prüft gespeicherte eigene Kurven: [{"name": str, "points": [[pos, tempo], …]}]; Kaputtes wird verworfen."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = " ".join(item["name"].split())[:MAX_NAME]
        if not name or name.lower() in seen:
            continue
        try:
            pts = normalize(item.get("points"))
        except SpeedRampError:
            continue
        seen.add(name.lower())
        out.append({"name": name, "points": [[round(p[0], 3), round(p[1], 4)] for p in pts]})
        if len(out) >= MAX_SAVED:
            break
    return out


def add_saved(saved, name: str, points) -> list[dict]:
    """Fügt eine Kurve hinzu oder ersetzt die gleichnamige; wirft SpeedRampError bei leerem Namen oder ungültiger Kurve."""
    name = " ".join((name or "").split())[:MAX_NAME]
    if not name:
        raise SpeedRampError("Bitte einen Namen für die Kurve eingeben.")
    pts = normalize(points)
    cur = [c for c in clean_saved(saved) if c["name"].lower() != name.lower()]
    if len(cur) >= MAX_SAVED:
        raise SpeedRampError(f"Es lassen sich höchstens {MAX_SAVED} eigene Kurven speichern – bitte eine löschen.")
    cur.append({"name": name, "points": [[round(p[0], 3), round(p[1], 4)] for p in pts]})
    return cur


def remove_saved(saved, name: str) -> list[dict]:
    return [c for c in clean_saved(saved) if c["name"].lower() != (name or "").strip().lower()]


def format_points(points) -> str:
    return ", ".join(f"{p[0]:g}:{p[1]:g}" for p in points)


def speed_at(points: list[list[float]], u: float) -> float:
    """Tempo an der Stelle u (0…1); zwischen den Punkten weich (Smoothstep)."""
    x = max(0.0, min(1.0, u)) * 100.0
    for a, b in zip(points, points[1:]):
        if x <= b[0] + 1e-9:
            f = 0.0 if b[0] - a[0] < 1e-9 else (x - a[0]) / (b[0] - a[0])
            f = f * f * (3.0 - 2.0 * f)
            return a[1] + (b[1] - a[1]) * f
    return points[-1][1]


def _duration_factor(points, a: float, b: float, steps: int = 64) -> float:
    """∫ du / Tempo(u) über [a, b] (Mittelpunktsregel) – so viel Zeitlinie (in Einheiten der Quelllänge) braucht der Abschnitt."""
    h = (b - a) / steps
    return sum(h / speed_at(points, a + (i + 0.5) * h) for i in range(steps))


# ---------------------------------------------------------------- Abschnitte
def pieces(points, src_len: float, base_speed: float = 1.0, max_pieces: int = MAX_PIECES) -> list[tuple[float, float, float]]:
    """Zerlegt die Kurve in [(Anfang 0…1, Ende 0…1, Tempo des Clips)] ohne Lücke und Überlappung."""
    pts = normalize(points)
    n = max(2, min(max_pieces, int(src_len / 0.15), 16))
    cuts = {round(i / n, 6) for i in range(n + 1)}
    cuts.update(round(p[0] / 100.0, 6) for p in pts)                  # Kurvenpunkte sind immer auch Schnittstellen
    cs = sorted(cuts)
    while len(cs) - 1 > max_pieces:                                    # zu viele: die kürzesten Abschnitte verschmelzen
        k = min(range(1, len(cs) - 1), key=lambda i: cs[i + 1] - cs[i - 1])
        del cs[k]
    out = []
    for a, b in zip(cs, cs[1:]):
        if b - a < 1e-6:
            continue
        eff = (b - a) / _duration_factor(pts, a, b)
        out.append((a, b, max(CLIP_MIN, min(CLIP_MAX, base_speed * eff))))
    return out


def new_length(points, src_len: float, base_speed: float = 1.0) -> float:
    """Länge des Clips auf der Timeline nach der Kurve (Sekunden)."""
    return sum((b - a) * src_len / sp for a, b, sp in pieces(points, src_len, base_speed))


def check_clip(c: Clip) -> None:
    if c.is_image:
        raise SpeedRampError("Standbilder haben kein Tempo.")
    if c.reverse:
        raise SpeedRampError("Rückwärts abgespielte Clips lassen sich nicht mit einer Kurve versehen – „Rückwärts“ zuerst ausschalten.")
    if c.out_pt - c.in_pt < MIN_SEGMENT:
        raise SpeedRampError(f"Der Clip ist zu kurz für eine Kurve (mindestens {MIN_SEGMENT:g} s).")


# ---------------------------------------------------------------- Anwenden
def _remap(keys: list, ease: bool, a: float, b: float):
    from .window import _remap_keys
    return _remap_keys(keys, ease, 1.0, a, b)


def _forget(c: Clip) -> None:
    c.ramp_id, c.ramp_pts, c.ramp_speed, c.ramp_keys, c.ramp_ease = "", [], 1.0, [], True


def group_of(project: Project, idx: int) -> tuple[int, int] | None:
    """(erster, letzter Index) der Abschnitte, die zur Kurve des Clips `idx` gehören – oder None, wenn der Clip zu keiner Kurve
    gehört oder die Abschnitte nicht mehr lückenlos hintereinander liegen (z. B. weil einer verschoben oder gekürzt wurde)."""
    if not 0 <= idx < len(project.clips):
        return None
    gid = project.clips[idx].ramp_id
    if not gid:
        return None
    lo = hi = idx
    while lo > 0 and project.clips[lo - 1].ramp_id == gid:
        lo -= 1
    while hi + 1 < len(project.clips) and project.clips[hi + 1].ramp_id == gid:
        hi += 1
    if any(c.ramp_id == gid for k, c in enumerate(project.clips) if not lo <= k <= hi):
        return None                                           # Abschnitte liegen verstreut
    for a, b in zip(project.clips[lo:hi], project.clips[lo + 1:hi + 1]):
        if a.path != b.path or abs(a.out_pt - b.in_pt) > 0.002 or a.reverse or b.reverse:
            return None                                       # Lücke oder Sprung in der Quelle
    return lo, hi


def curve_of(project: Project, idx: int) -> list[list[float]] | None:
    """Die gemerkte Kurve des Clips (für die Anzeige) oder None."""
    g = group_of(project, idx)
    return [list(q) for q in project.clips[g[0]].ramp_pts] if g else None


def merge_group(project: Project, idx: int) -> int:
    """Führt alle Abschnitte der Kurve wieder zu einem Clip zusammen (Anfang, Ende, Grundtempo, Bewegung wie vor der Kurve);
    gibt den Index des Clips zurück."""
    g = group_of(project, idx)
    if g is None:
        raise SpeedRampError("Dieser Clip gehört zu keiner Kurve, oder die Abschnitte wurden verändert.")
    lo, hi = g
    first, last = project.clips[lo], project.clips[hi]
    first.out_pt = last.out_pt
    first.speed = first.ramp_speed
    first.transition, first.transition_dur = last.transition, last.transition_dur
    first.keyframes, first.motion_ease = copy.deepcopy(first.ramp_keys), first.ramp_ease
    _forget(first)
    del project.clips[lo + 1:hi + 1]
    project.sync_linked()
    return lo


def apply(project: Project, idx: int, points) -> list[int]:
    """Teilt den Clip `idx` nach der Kurve; gibt die Indizes der neuen Abschnitte zurück. Ein getrennter Ton wird dabei
    wieder mit dem Clip verbunden."""
    if not 0 <= idx < len(project.clips):
        raise SpeedRampError("Kein Clip gewählt.")
    pts = normalize(points)
    grp = group_of(project, idx)
    if grp:                                    # gehört schon zu einer Kurve: erst zusammenführen, dann neu teilen
        idx = merge_group(project, idx)
    elif project.clips[idx].ramp_id:           # veraltete Spur einer Kurve (Abschnitte wurden verändert): vergessen
        _forget(project.clips[idx])
    c = project.clips[idx]
    check_clip(c)
    if c.audio_detached:
        project.reattach_audio(idx)
    seg = c.out_pt - c.in_pt
    parts = pieces(pts, seg, c.speed)
    base_in, last_trans, last_dur = c.in_pt, c.transition, c.transition_dur
    keys, ease = list(c.keyframes or []), c.motion_ease
    gid, base_speed = uuid.uuid4().hex[:10], c.speed
    new: list[Clip] = []
    for k, (a, b, sp) in enumerate(parts):
        piece = c if k == 0 else copy.deepcopy(c)
        if k > 0:
            piece.uid = uuid.uuid4().hex[:10]
        piece.ramp_id, piece.ramp_pts, piece.ramp_speed = gid, [list(q) for q in pts], base_speed
        piece.ramp_keys, piece.ramp_ease = copy.deepcopy(keys), ease
        piece.in_pt = base_in + a * seg
        piece.out_pt = base_in + b * seg if k < len(parts) - 1 else base_in + seg
        piece.speed = round(sp, 4)
        piece.transition, piece.transition_dur = ("", c.transition_dur) if k < len(parts) - 1 else (last_trans, last_dur)
        if keys:
            piece.keyframes, piece.motion_ease = _remap(keys, ease, a, b)
        new.append(piece)
    project.clips[idx:idx + 1] = new
    project.sync_linked()
    return list(range(idx, idx + len(new)))
