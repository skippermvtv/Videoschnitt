"""Pipette: Farbe aus einem Standbild wählen (Umrechnung der Mausposition, Mittelwert um den Klickpunkt)."""
from __future__ import annotations

from . import maskgeom


def map_click(px: float, py: float, widget_w: float, widget_h: float, img_w: int, img_h: int) -> tuple[int, int] | None:
    """Mausposition im Anzeigefeld → Bildpunkt im Standbild; None, wenn neben dem Bild (schwarze Ränder) geklickt wurde."""
    if img_w <= 0 or img_h <= 0 or widget_w <= 0 or widget_h <= 0:
        return None
    x, y, w, h = maskgeom.fit_rect(widget_w, widget_h, img_w, img_h)
    if w <= 0 or h <= 0 or not (x <= px < x + w and y <= py < y + h):
        return None
    ix = min(img_w - 1, max(0, int((px - x) / w * img_w)))
    iy = min(img_h - 1, max(0, int((py - y) / h * img_h)))
    return ix, iy


def neighborhood(ix: int, iy: int, img_w: int, img_h: int, radius: int = 2) -> list[tuple[int, int]]:
    """Bildpunkte im Quadrat um den Klickpunkt (am Bildrand abgeschnitten) – der Mittelwert dämpft Bildrauschen."""
    return [(x, y) for y in range(max(0, iy - radius), min(img_h, iy + radius + 1))
            for x in range(max(0, ix - radius), min(img_w, ix + radius + 1))]


def average_hex(rgb: list[tuple[int, int, int]]) -> str:
    """Mittelwert der Farben als „#rrggbb“."""
    if not rgb:
        return "#000000"
    n = len(rgb)
    r, g, b = (round(sum(c[i] for c in rgb) / n) for i in range(3))
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"
