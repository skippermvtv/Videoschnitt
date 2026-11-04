"""Zeitfenster-Projekt: schneidet ein Projekt auf einen kurzen Abschnitt zu.

Die Live-Vorschau rechnet nach jeder Änderung nur ein paar Sekunden am Abspielkopf neu. Damit das auch bei
langen Projekten schnell geht, enthält das Fenster-Projekt nur die Clips, Texte, Untertitel, Overlays und
Tonblöcke, die in den Abschnitt fallen – alle Zeiten sind um den Fensteranfang verschoben.

Wichtig ist, dass das Bild im Fenster dasselbe zeigt wie im vollen Projekt. Darum werden Übergänge nie
„angeschnitten“: Fenster beginnen und enden so, dass die Überlappung zweier Clips immer vollständig im
Fenster liegt (siehe snap_start / snap_end). Wo das nicht gelingt, nimmt das Fenster das ganze Projekt.
"""
from __future__ import annotations

import copy
from dataclasses import replace

from .project import Project

EPS = 1e-6
MIN_KEEP = 0.05          # kürzestes Stück eines Clips im Fenster


def _layout(p: Project) -> tuple[list[float], list[float], list[float], list[float]]:
    starts = [p.clip_start(i) for i in range(len(p.clips))]
    lens = [c.length for c in p.clips]
    ends = [s + n for s, n in zip(starts, lens)]
    outs = [p.overlap_after(i) for i in range(len(p.clips))]
    return starts, lens, ends, outs


def snap_start(p: Project, t0: float) -> float:
    """Frühester sicherer Fensteranfang ≤ t0 (0.0 = ganzes Projekt von vorn)."""
    n = len(p.clips)
    if n == 0 or t0 <= EPS:
        return 0.0
    S, _L, E, D = _layout(p)
    cur = min(t0, E[-1] - EPS)
    for _ in range(8):
        j = next((k for k in range(n) if E[k] > cur + EPS), n - 1)
        if cur <= S[j] + EPS:
            return max(0.0, cur)
        need = (2.0 * D[j] if D[j] > 0 else 0.0) + MIN_KEEP     # so viel muss vom Clip bleiben, damit der Übergang gleich lang bleibt
        allowed = E[j] - need
        if cur <= allowed + EPS:
            return cur
        cur = max(S[j], allowed)
        if cur <= EPS:
            return 0.0
    return 0.0


def snap_end(p: Project, t1: float) -> float:
    """Spätestes sicheres Fensterende ≥ t1 (Projektende, wenn es nicht anders geht)."""
    n = len(p.clips)
    total = p.duration
    if n == 0 or t1 >= total - EPS:
        return total
    S, _L, E, D = _layout(p)
    cur = max(t1, MIN_KEEP)
    for _ in range(8):
        k = max((i for i in range(n) if S[i] < cur - EPS), default=0)
        d_in = D[k - 1] if k > 0 else 0.0
        need = (2.0 * d_in if d_in > 0 else 0.0) + MIN_KEEP
        want = max(cur, S[k] + need)
        if want <= cur + EPS:
            return min(cur, total)
        cur = want
        if cur >= total - EPS:
            return total
    return total


# ----------------------------------------------------------------- Keyframes
def _value_at(keys: list[dict], field: str, u: float, ease: bool) -> float:
    pts = sorted((max(0.0, min(1.0, float(k.get("t", 0)))), float(k.get(field, 100.0 if field == "zoom" else 0.0)))
                 for k in keys)
    if u <= pts[0][0]:
        return pts[0][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if u <= t1:
            x = (u - t0) / max(t1 - t0, 1e-3)
            if ease:
                x = x * x * (3 - 2 * x)
            return v0 + (v1 - v0) * x
    return pts[-1][1]


def _remap_keys(keys: list, ease: bool, length: float, a: float, b: float) -> tuple[list, bool]:
    """Keyframes (Zeit 0…1 über die Clip-Länge) für den Ausschnitt [a, b] des Clips neu berechnen.

    Gibt (neue Keyframes, weiche Übergänge?) zurück. Bei weichen Übergängen wird die Kurve mehrfach abgetastet und
    linear nachgebildet – ein abgeschnittenes Stück einer weichen Kurve hat sonst eine andere Form.
    """
    good = [k for k in keys if isinstance(k, dict)]
    span = b - a
    if not good or span <= EPS or length <= EPS:
        return keys, ease
    fields = ("zoom", "x", "y", "rot")
    times = {0.0, 1.0}
    for k in good:
        t_new = (float(k.get("t", 0)) * length - a) / span
        if EPS < t_new < 1.0 - EPS:
            times.add(round(t_new, 6))
    if ease:
        times.update(i / 16.0 for i in range(1, 16))
    out = []
    for tt in sorted(times):
        u = (a + tt * span) / length
        k = {f: _value_at(good, f, u, ease) for f in fields}
        k["t"] = tt
        out.append(k)
    return out, (False if ease else ease)


# ------------------------------------------------------------------- Fenster
def project_window(p: Project, t0: float, length: float) -> tuple[Project, float, float]:
    """Gibt (Fenster-Projekt, Versatz von t0 im Fenster, Länge des Ergebnisses) zurück.

    Rendert man das Fenster-Projekt ab `Versatz` für `Länge` Sekunden, entspricht das dem vollen Projekt von
    t0 bis t0 + Länge.
    """
    total = p.duration
    if not p.clips or total <= 0:
        return copy.deepcopy(p), 0.0, 0.0
    t0 = max(0.0, min(float(t0), max(0.0, total - 0.05)))
    length = max(0.5, float(length))
    t1 = min(total, t0 + length)
    w0 = snap_start(p, t0)
    w1 = snap_end(p, t1)
    wlen = w1 - w0
    S, L, E, _D = _layout(p)

    out = Project(format_id=p.format_id, export_id=p.export_id, layout=p.layout, look_id=p.look_id,
                  track_volume=dict(p.track_volume), track_mute=dict(p.track_mute), ducking=p.ducking,
                  ducking_amount=p.ducking_amount, normalize=p.normalize,
                  fade_in=p.fade_in if w0 <= EPS else 0.0,
                  fade_out=p.fade_out if w1 >= total - EPS else 0.0,
                  sub_style=copy.deepcopy(p.sub_style))

    # --- Clips
    for k, c in enumerate(p.clips):
        if E[k] <= w0 + EPS or S[k] >= w1 - EPS:
            continue
        a = max(0.0, w0 - S[k])
        b = min(L[k], w1 - S[k])
        nc = copy.deepcopy(c)
        if a > EPS or b < L[k] - EPS:
            sp = max(c.speed, 0.01)
            if c.reverse:
                nc.in_pt, nc.out_pt = c.out_pt - b * sp, c.out_pt - a * sp
            else:
                nc.in_pt, nc.out_pt = c.in_pt + a * sp, c.in_pt + b * sp
            if c.keyframes:
                nc.keyframes, nc.motion_ease = _remap_keys(c.keyframes, c.motion_ease, L[k], a, b)
        out.clips.append(nc)

    # --- Effekt-Blöcke (Zeiten verschieben; Masken mit Pfad behalten ihren Zeitbezug)
    for e in p.effects:
        ne = copy.deepcopy(e)
        s, t = e.get("start"), e.get("end")
        if s is None and t is None:
            if isinstance(e.get("mask"), dict) and e["mask"].get("track"):
                ne["start"] = round(-w0, 3)
            out.effects.append(ne)
            continue
        s2 = (0.0 if s is None else float(s)) - w0
        t2 = None if t is None else float(t) - w0
        if t2 is not None and t2 <= 0.0:
            continue
        if s2 >= wlen:
            continue
        if not (isinstance(e.get("mask"), dict) and e["mask"].get("track")):
            s2 = max(0.0, s2)
        ne["start"] = round(s2, 3)
        ne["end"] = None if t2 is None else round(t2, 3)
        out.effects.append(ne)

    # --- Texte und Untertitel
    for tl in p.texts:
        s2, e2 = tl.start - w0, tl.end - w0
        if e2 > 0.0 and s2 < wlen:
            out.texts.append(replace(tl, start=s2, end=e2))
    for cue in p.subtitles:
        s2, e2 = cue.start - w0, cue.end - w0
        if e2 > 0.0 and s2 < wlen:
            out.subtitles.append(replace(cue, start=s2, end=e2))

    # --- Bild-in-Bild
    for o in p.overlays:
        s2 = o.start - w0
        olen = o.length
        if s2 + olen <= 0.0 or s2 >= wlen:
            continue
        no = copy.deepcopy(o)
        if s2 < 0.0:
            cut = -s2
            no.in_pt = o.in_pt + cut * max(o.speed, 0.01)
            if no.out_pt - no.in_pt < MIN_KEEP:
                continue
            no.fade_in = max(0.0, o.fade_in - cut)
            s2 = 0.0
        no.start = s2
        out.overlays.append(no)

    # --- Tonblöcke
    for a_ in p.audio_clips:
        s2 = a_.start - w0
        alen = a_.length
        if not a_.loop and s2 + alen <= 0.0:
            continue
        if s2 >= wlen:
            continue
        na = copy.deepcopy(a_)
        if s2 < 0.0:
            if not a_.loop:
                cut = -s2
                sp = max(a_.speed, 0.01)
                if a_.reverse:
                    na.out_pt = a_.out_pt - cut * sp
                else:
                    na.in_pt = a_.in_pt + cut * sp
                if na.out_pt - na.in_pt < MIN_KEEP:
                    continue
                na.fade_in = max(0.0, a_.fade_in - cut)
            s2 = 0.0
        na.start = s2
        out.audio_clips.append(na)

    return out, t0 - w0, t1 - t0
