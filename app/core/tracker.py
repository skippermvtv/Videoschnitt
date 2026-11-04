"""Objektverfolgung (Tracking) für Masken: ein Bereich wandert mit einem Objekt im Bild mit.

Verfahren: Vorlage aus dem ersten Bild (der Maskenrahmen), in jedem weiteren Bild wird die Stelle mit der höchsten
normierten Kreuzkorrelation (NCC) in der Nähe der letzten Position gesucht. Gerechnet wird auf kleinen Graustufenbildern.
Braucht numpy (wird erst beim Verfolgen geladen).
"""
from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MAX_SECONDS = 30.0        # längste verfolgte Strecke
MAX_POINTS = 40           # so viele Pfadpunkte bleiben höchstens übrig
LOST_BELOW = 0.35         # Treffer schwächer als das → Objekt verloren, Position bleibt stehen
ADAPT_ABOVE = 0.88        # sehr sicherer Treffer → Vorlage leicht nachführen (gegen Drehen/Helligkeit)


class TrackError(Exception):
    pass


@dataclass
class TrackResult:
    points: list          # [[t, x%, y%], …] ab Blockanfang
    frames: int
    lost: int             # Bilder, in denen das Objekt nicht sicher gefunden wurde
    seconds: float


# ---------------------------------------------------------------- Korrelation
def ncc_map(region, tmpl):
    """NCC jeder Position (gültiger Bereich) der Vorlage in `region`; Werte −1…1."""
    import numpy as np
    region = region.astype(np.float64)
    t = tmpl.astype(np.float64)
    th, tw = t.shape
    h, w = region.shape
    if h < th or w < tw:
        raise TrackError("Suchbereich kleiner als die Vorlage")
    t0 = t - t.mean()
    tn = float(np.sqrt((t0 * t0).sum()))
    if tn < 1e-6:                                         # einfarbige Vorlage: nichts zu verfolgen
        return np.zeros((h - th + 1, w - tw + 1))
    shape = (h + th, w + tw)
    f = np.fft.rfft2(region, shape)
    g = np.fft.rfft2(t0[::-1, ::-1], shape)
    corr = np.fft.irfft2(f * g, shape)[th - 1:h, tw - 1:w]

    def box_sum(a):
        ii = np.zeros((a.shape[0] + 1, a.shape[1] + 1))
        ii[1:, 1:] = a.cumsum(0).cumsum(1)
        return ii[th:, tw:] - ii[:-th, tw:] - ii[th:, :-tw] + ii[:-th, :-tw]
    n = th * tw
    s1 = box_sum(region)
    s2 = box_sum(region * region)
    var = np.maximum(s2 - s1 * s1 / n, 1e-6)
    return corr / (np.sqrt(var) * tn)


def follow(frames, box: tuple[float, float, float, float], search: float = 0.18,
           should_cancel: Callable[[], bool] | None = None,
           on_progress: Callable[[float], None] | None = None):
    """Verfolgt `box` = (Mitte x, Mitte y, Breite, Höhe) in Bildpunkten durch `frames` (n, H, W).

    Gibt (Positionen [(x, y)] je Bild in Bildpunkten, Anzahl verlorener Bilder) zurück.
    """
    import numpy as np
    n, H, W = frames.shape
    cx, cy, bw, bh = box
    tw = int(max(8, min(round(bw), W - 2)))
    th = int(max(8, min(round(bh), H - 2)))
    x0 = int(round(min(max(cx - tw / 2, 0), W - tw)))
    y0 = int(round(min(max(cy - th / 2, 0), H - th)))
    tmpl = frames[0][y0:y0 + th, x0:x0 + tw].astype(np.float64)
    pos = [(x0 + tw / 2, y0 + th / 2)]
    last = pos[0]
    lost = 0
    rad = max(10, int(search * max(W, H)))
    for i in range(1, n):
        if should_cancel and should_cancel():
            raise TrackError("Abgebrochen")
        ax = int(max(0, round(last[0] - tw / 2) - rad))
        ay = int(max(0, round(last[1] - th / 2) - rad))
        bx = int(min(W, round(last[0] + tw / 2) + rad))
        by = int(min(H, round(last[1] + th / 2) + rad))
        region = frames[i][ay:by, ax:bx]
        if region.shape[0] < th or region.shape[1] < tw:
            pos.append(last)
            lost += 1
            continue
        m = ncc_map(region, tmpl)
        k = int(np.argmax(m))
        iy, ix = divmod(k, m.shape[1])
        peak = float(m[iy, ix])
        if peak < LOST_BELOW:
            lost += 1
            pos.append(last)
        else:
            last = (ax + ix + tw / 2, ay + iy + th / 2)
            pos.append(last)
            if peak > ADAPT_ABOVE:
                new = frames[i][ay + iy:ay + iy + th, ax + ix:ax + ix + tw].astype(np.float64)
                tmpl = 0.9 * tmpl + 0.1 * new
        if on_progress and i % 4 == 0:
            on_progress(i / max(1, n - 1))
    return pos, lost


# ---------------------------------------------------------------- Pfad aufbereiten
def smooth(points: list, window: int = 5) -> list:
    """Gleitender Mittelwert über x und y (Zeit bleibt)."""
    if len(points) < 3 or window < 3:
        return [list(p) for p in points]
    h = window // 2
    out = []
    for i, p in enumerate(points):
        a, b = max(0, i - h), min(len(points), i + h + 1)
        seg = points[a:b]
        out.append([p[0], sum(q[1] for q in seg) / len(seg), sum(q[2] for q in seg) / len(seg)])
    return out


def _dev(points: list, a: int, b: int, k: int) -> float:
    """Abstand des Punktes k von der Geraden a→b zur gleichen Zeit (größerer Wert von x und y)."""
    ta, tb = points[a][0], points[b][0]
    u = 0.0 if tb - ta < 1e-9 else (points[k][0] - ta) / (tb - ta)
    ex = points[a][1] + (points[b][1] - points[a][1]) * u
    ey = points[a][2] + (points[b][2] - points[a][2]) * u
    return max(abs(points[k][1] - ex), abs(points[k][2] - ey))


def simplify(points: list, tol: float) -> list:
    """Ramer-Douglas-Peucker mit Zeitbezug: lässt nur Punkte, die mehr als `tol` (%) vom Verlauf abweichen."""
    n = len(points)
    if n <= 2:
        return [list(p) for p in points]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        worst, wi = 0.0, -1
        for k in range(a + 1, b):
            d = _dev(points, a, b, k)
            if d > worst:
                worst, wi = d, k
        if wi >= 0 and worst > tol:
            keep[wi] = True
            stack.append((a, wi))
            stack.append((wi, b))
    return [list(p) for p, kp in zip(points, keep) if kp]


def reduce_points(points: list, limit: int = MAX_POINTS, tol: float = 0.2) -> list:
    pts = simplify(points, tol)
    while len(pts) > limit:
        tol *= 1.4
        pts = simplify(points, tol)
    return [[round(p[0], 3), round(p[1], 2), round(p[2], 2)] for p in pts]


# ---------------------------------------------------------------- Ganzer Ablauf für einen Effekt-Block
def track_block(project, idx: int, *, height: int = 270, fps: float = 12.0,
                should_cancel: Callable[[], bool] | None = None,
                on_progress: Callable[[float], None] | None = None) -> TrackResult:
    """Verfolgt den Maskenbereich des Effekt-Blocks `idx` über die Länge des Blocks (höchstens 30 s)."""
    try:
        import numpy  # noqa: F401
    except ImportError as exc:
        raise TrackError("Für das Tracking fehlt numpy (im installierten Programm enthalten).") from exc
    from . import effects as fx, frames
    from .project import probe
    if not 0 <= idx < len(project.effects):
        raise TrackError("Kein Effekt-Block gewählt.")
    e = project.effects[idx]
    eff = fx.REGISTRY.get(e["id"])
    if not (eff and eff.params):
        raise TrackError("Dieser Effekt hat keinen Bereich.")
    s0, t0 = project.fx_span(idx)
    length = min(max(0.0, t0 - s0), MAX_SECONDS, max(0.0, project.duration - s0))
    if length < 0.3:
        raise TrackError("Der Block ist zu kurz zum Verfolgen.")
    m = fx.mask_params(e.get("mask"))
    sx, sy = (m["track"][0][1], m["track"][0][2]) if m["track"] else (m["x"], m["y"])
    tmp = Path(tempfile.mkdtemp(prefix="fate_track_"))
    try:
        mp4 = str(tmp / "seg.mp4")
        frames.render_segment(project, s0, length, height, mp4, should_cancel,
                              (lambda p: on_progress(p * 0.5)) if on_progress else None)
        info = probe(mp4)
        W, H = int(info.width), int(info.height)
        arr = frames.read_gray(mp4, fps, W, H)
        if len(arr) < 2:
            raise TrackError("Zu wenige Bilder zum Verfolgen.")
        box = (sx / 100.0 * W, sy / 100.0 * H, m["w"] / 100.0 * W, m["h"] / 100.0 * H)
        pos, lost = follow(arr, box, should_cancel=should_cancel,
                           on_progress=(lambda p: on_progress(0.5 + p * 0.5)) if on_progress else None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    pts = [[i / fps, x / W * 100.0, y / H * 100.0] for i, (x, y) in enumerate(pos)]
    pts = reduce_points(smooth(pts))
    return TrackResult(points=pts, frames=len(pos), lost=lost, seconds=length)


def cleanup_temp() -> None:
    """Übrig gebliebene Arbeitsordner löschen (nach Absturz)."""
    base = Path(tempfile.gettempdir())
    for d in base.glob("fate_track_*"):
        shutil.rmtree(d, ignore_errors=True)
