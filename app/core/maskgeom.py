"""Geometrie der Masken-Bearbeitung im Vorschaubild (ohne Qt, damit die Tests sie prüfen können).

Eine Maske ist ein Dict mit x, y (Mitte) sowie w, h (Breite/Höhe), alles in % des Bildes. Der Bearbeitungsrahmen
zeigt die Form; man kann ihn in der Mitte verschieben und an Rändern und Ecken in der Größe ziehen.
"""
from __future__ import annotations

MIN_SIZE = 2.0          # kleinste Breite/Höhe in %
MAX_SIZE = 200.0

MODES = ("tl", "t", "tr", "l", "r", "bl", "b", "br", "move")


def box(m: dict) -> tuple[float, float, float, float]:
    """(links, oben, rechts, unten) in %."""
    x, y, w, h = float(m["x"]), float(m["y"]), float(m["w"]), float(m["h"])
    return x - w / 2, y - h / 2, x + w / 2, y + h / 2


def hit(m: dict, width: float, height: float, px: float, py: float, tol: float = 9.0) -> str | None:
    """Welcher Teil des Rahmens liegt unter dem Punkt (px, py) in Bildpunkten? None = daneben."""
    if width <= 0 or height <= 0:
        return None
    l, t, r, b = box(m)
    l, r = l / 100.0 * width, r / 100.0 * width
    t, b = t / 100.0 * height, b / 100.0 * height
    near_l, near_r = abs(px - l) <= tol, abs(px - r) <= tol
    near_t, near_b = abs(py - t) <= tol, abs(py - b) <= tol
    in_x, in_y = l - tol <= px <= r + tol, t - tol <= py <= b + tol
    if near_l and near_t:
        return "tl"
    if near_r and near_t:
        return "tr"
    if near_l and near_b:
        return "bl"
    if near_r and near_b:
        return "br"
    if near_t and in_x:
        return "t"
    if near_b and in_x:
        return "b"
    if near_l and in_y:
        return "l"
    if near_r and in_y:
        return "r"
    if l < px < r and t < py < b:
        return "move"
    return None


def drag(m: dict, mode: str, dx: float, dy: float) -> dict:
    """Neue Maske nach Ziehen um (dx, dy) in % des Bildes (vom Zustand beim Anfassen aus gerechnet)."""
    out = dict(m)
    if mode == "move":
        out["x"] = min(100.0, max(0.0, float(m["x"]) + dx))
        out["y"] = min(100.0, max(0.0, float(m["y"]) + dy))
        return out
    l, t, r, b = box(m)
    if "l" in mode:
        l = min(l + dx, r - MIN_SIZE)
    if "r" in mode:
        r = max(r + dx, l + MIN_SIZE)
    if mode in ("t", "tl", "tr"):
        t = min(t + dy, b - MIN_SIZE)
    if mode in ("b", "bl", "br"):
        b = max(b + dy, t + MIN_SIZE)
    w, h = min(MAX_SIZE, r - l), min(MAX_SIZE, b - t)
    out["w"], out["h"] = w, h
    out["x"] = min(100.0, max(0.0, (l + r) / 2))
    out["y"] = min(100.0, max(0.0, (t + b) / 2))
    return out


def cursor_name(mode: str | None) -> str:
    """Name der Mauszeigerform: 'size_fdiag', 'size_bdiag', 'size_hor', 'size_ver', 'size_all', 'arrow'."""
    return {"tl": "size_fdiag", "br": "size_fdiag", "tr": "size_bdiag", "bl": "size_bdiag", "l": "size_hor",
            "r": "size_hor", "t": "size_ver", "b": "size_ver", "move": "size_all"}.get(mode or "", "arrow")


def fit_rect(widget_w: float, widget_h: float, img_w: float, img_h: float) -> tuple[float, float, float, float]:
    """Wo das Bild (mit Seitenverhältnis) im Widget liegt: (x, y, Breite, Höhe)."""
    if img_w <= 0 or img_h <= 0 or widget_w <= 0 or widget_h <= 0:
        return 0.0, 0.0, max(widget_w, 1.0), max(widget_h, 1.0)
    s = min(widget_w / img_w, widget_h / img_h)
    w, h = img_w * s, img_h * s
    return (widget_w - w) / 2, (widget_h - h) / 2, w, h
