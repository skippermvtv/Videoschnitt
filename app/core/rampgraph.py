"""Rechenkern des Kurven-Editors für die Geschwindigkeitskurve (ohne Qt, damit er sich testen lässt).

Die Zeichenfläche hat links die Position im Clip (0–100 %) und senkrecht das Tempo auf einer logarithmischen Achse
(×0,1 … ×8): so liegt ×0,5 genauso weit unter ×1 wie ×2 darüber.
"""
from __future__ import annotations

import math

from .speedramp import MAX_SPEED, MIN_SPEED

MIN_GAP = 1.0            # Mindestabstand zweier Punkte in % (Anfang und Ende bleiben bei 0 und 100)
MAX_POINTS = 12
_LO, _HI = math.log(MIN_SPEED), math.log(MAX_SPEED)


def speed_to_v(speed: float) -> float:
    """Tempo → senkrechte Lage 0 (unten, ×0,1) … 1 (oben, ×8)."""
    s = max(MIN_SPEED, min(MAX_SPEED, speed))
    return (math.log(s) - _LO) / (_HI - _LO)


def v_to_speed(v: float) -> float:
    return math.exp(_LO + max(0.0, min(1.0, v)) * (_HI - _LO))


def to_px(point, w: float, h: float) -> tuple[float, float]:
    """[Position %, Tempo] → Pixel (y von oben)."""
    return point[0] / 100.0 * w, (1.0 - speed_to_v(point[1])) * h


def from_px(x: float, y: float, w: float, h: float) -> tuple[float, float]:
    """Pixel → (Position %, Tempo); auf den Zeichenbereich begrenzt."""
    pos = max(0.0, min(100.0, x / max(1.0, w) * 100.0))
    return pos, v_to_speed(1.0 - y / max(1.0, h))


def hit(points, x: float, y: float, w: float, h: float, radius: float = 9.0) -> int:
    """Index des Punkts unter (x, y) oder -1; bei Gleichstand der nächste."""
    best, best_d = -1, radius * radius
    for i, p in enumerate(points):
        px, py = to_px(p, w, h)
        d = (px - x) ** 2 + (py - y) ** 2
        if d <= best_d:
            best, best_d = i, d
    return best


def rounded(points) -> list[list[float]]:
    """Für die Anzeige im Textfeld: Position auf 0,1 %, Tempo auf 2 Stellen."""
    return [[round(p[0], 1), round(p[1], 2)] for p in points]


def move(points, i: int, pos: float, speed: float) -> list[list[float]]:
    """Verschiebt Punkt i. Der erste und letzte Punkt bleiben bei 0 % und 100 % (nur das Tempo ändert sich);
    die übrigen bleiben zwischen ihren Nachbarn."""
    pts = [list(p) for p in points]
    speed = max(MIN_SPEED, min(MAX_SPEED, speed))
    if i <= 0:
        pts[0] = [0.0, speed]
    elif i >= len(pts) - 1:
        pts[-1] = [100.0, speed]
    else:
        lo, hi = pts[i - 1][0] + MIN_GAP, pts[i + 1][0] - MIN_GAP
        pts[i] = [max(lo, min(hi, pos)), speed]
    return pts


def add(points, pos: float, speed: float) -> tuple[list[list[float]], int]:
    """Neuer Punkt; gibt (Punkte, Index) zurück. Liegt er zu nah an einem anderen oder gibt es schon MAX_POINTS, bleibt alles
    unverändert (Index -1)."""
    pts = [list(p) for p in points]
    if len(pts) >= MAX_POINTS or not 0.0 < pos < 100.0:
        return pts, -1
    if any(abs(p[0] - pos) < MIN_GAP for p in pts):
        return pts, -1
    pts.append([pos, max(MIN_SPEED, min(MAX_SPEED, speed))])
    pts.sort(key=lambda q: q[0])
    return pts, next(i for i, p in enumerate(pts) if p[0] == pos)


def remove(points, i: int) -> list[list[float]]:
    """Entfernt Punkt i; Anfang und Ende sowie die letzten zwei Punkte bleiben."""
    pts = [list(p) for p in points]
    if 0 < i < len(pts) - 1 and len(pts) > 2:
        del pts[i]
    return pts


def polyline(points, w: float, h: float, steps: int = 120) -> list[tuple[float, float]]:
    """Die weiche Kurve als Pixelzug (dieselbe Überblendung wie beim Export)."""
    from .speedramp import speed_at
    return [(k / steps * w, (1.0 - speed_to_v(speed_at(points, k / steps))) * h) for k in range(steps + 1)]


GRID_SPEEDS = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
