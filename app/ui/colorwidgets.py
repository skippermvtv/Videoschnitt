"""Bedienelemente für die Farbkorrektur: Farbrad und Kurven-Editor (ab 1.3).

Die Rechenteile (Punkte verschieben, Farbrad ↔ RGB, Kurvenverlauf) sind reine Funktionen ohne Qt und werden
in tests/test_color13_logic.py geprüft; die Widgets selbst ruft nur die Oberfläche auf.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ..core import grade as gradelib
from .theme import ACCENT, MUTED

CHANNEL_COLORS = {"m": "#e6e6e6", "r": "#ff5a5a", "g": "#5ad65a", "b": "#5a8cff"}
POINT_RADIUS = 6.0


# ------------------------------------------------------------------ Farbrad: reine Rechnung
def rgb_from_xy(x: float, y: float) -> tuple[int, int, int]:
    """Punkt im Rad (x nach rechts, y nach oben, Radius 1) → Verschiebung je Kanal -100 … +100 (Summe ≈ 0)."""
    s = min(1.0, math.hypot(x, y))
    if s < 1e-9:
        return 0, 0, 0
    th = math.atan2(y, x)
    return tuple(int(round(100.0 * s * math.cos(th - k * 2.0 * math.pi / 3.0))) for k in range(3))  # type: ignore[return-value]


def xy_from_rgb(r: float, g: float, b: float) -> tuple[float, float]:
    """Gegenstück zu rgb_from_xy; Ergebnis liegt immer im Einheitskreis."""
    x = (r - (g + b) / 2.0) / 150.0
    y = (g - b) / (100.0 * math.sqrt(3.0))
    d = math.hypot(x, y)
    if d > 1.0:
        x, y = x / d, y / d
    return x, y


# ------------------------------------------------------------------ Kurven: reine Rechnung
def add_point(points: list[list[float]], x: float, y: float) -> int:
    """Fügt einen Punkt ein und gibt seinen Index zurück (bei zu vielen/zu nahen Punkten: -1)."""
    pts = points
    if len(pts) >= gradelib.CURVE_MAX_POINTS:
        return -1
    x, y = min(1.0, max(0.0, x)), min(1.0, max(0.0, y))
    for p in pts:
        if abs(p[0] - x) < 0.02:
            return -1
    pts.append([x, y])
    pts.sort(key=lambda q: q[0])
    return next(i for i, p in enumerate(pts) if p[0] == x and p[1] == y)


def move_point(points: list[list[float]], idx: int, x: float, y: float) -> None:
    """Verschiebt einen Punkt; die Randpunkte behalten x=0 bzw. x=1, alle anderen bleiben zwischen den Nachbarn."""
    if not 0 <= idx < len(points):
        return
    y = min(1.0, max(0.0, y))
    if idx == 0:
        x = 0.0
    elif idx == len(points) - 1:
        x = 1.0
    else:
        x = min(points[idx + 1][0] - 0.02, max(points[idx - 1][0] + 0.02, x))
    points[idx] = [x, y]


def remove_point(points: list[list[float]], idx: int) -> bool:
    """Löscht einen inneren Punkt (die Randpunkte bleiben)."""
    if 0 < idx < len(points) - 1:
        del points[idx]
        return True
    return False


def nearest_point(points: list[list[float]], x: float, y: float, rx: float, ry: float) -> int:
    """Index des Punkts innerhalb des Fangradius (rx, ry in Kurven-Einheiten) oder -1."""
    best, best_d = -1, 1.0
    for i, p in enumerate(points):
        d = math.hypot((p[0] - x) / rx, (p[1] - y) / ry)
        if d <= 1.0 and d < best_d:
            best, best_d = i, d
    return best


def spline(points: list[list[float]], n: int = 64) -> list[tuple[float, float]]:
    """Natürlicher kubischer Spline durch die Punkte – so zeichnet auch FFmpegs „curves“-Filter."""
    pts = gradelib.normalize_points(points)
    m = len(pts)
    if m < 3:
        return [(x, y) for x, y in pts]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    h = [xs[i + 1] - xs[i] for i in range(m - 1)]
    alpha = [0.0] * m
    for i in range(1, m - 1):
        alpha[i] = 3.0 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
    l_ = [1.0] + [0.0] * (m - 1)
    mu = [0.0] * m
    z = [0.0] * m
    for i in range(1, m - 1):
        l_[i] = 2.0 * (xs[i + 1] - xs[i - 1]) - h[i - 1] * mu[i - 1]
        mu[i] = h[i] / l_[i]
        z[i] = (alpha[i] - h[i - 1] * z[i - 1]) / l_[i]
    c = [0.0] * m
    b = [0.0] * (m - 1)
    d = [0.0] * (m - 1)
    for j in range(m - 2, -1, -1):
        c[j] = z[j] - mu[j] * c[j + 1]
        b[j] = (ys[j + 1] - ys[j]) / h[j] - h[j] * (c[j + 1] + 2.0 * c[j]) / 3.0
        d[j] = (c[j + 1] - c[j]) / (3.0 * h[j])
    out = []
    seg = 0
    for k in range(n + 1):
        x = k / n
        while seg < m - 2 and x > xs[seg + 1]:
            seg += 1
        t = x - xs[seg]
        y = ys[seg] + b[seg] * t + c[seg] * t * t + d[seg] * t ** 3
        out.append((x, min(1.0, max(0.0, y))))
    return out


# ------------------------------------------------------------------ Widgets
class ColorWheel(QWidget):
    """Farbrad für Schatten, Mitten oder Lichter. Ziehen verschiebt die Farbe, Doppelklick setzt zurück."""

    changed = Signal(int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rgb = (0, 0, 0)
        self._drag = False
        self.setMinimumSize(80, 90)
        self.setToolTip("Ziehen: Farbe verschieben · Doppelklick: zurücksetzen")

    def rgb(self) -> tuple[int, int, int]:
        return self._rgb

    def set_rgb(self, r: int, g: int, b: int) -> None:
        """Setzt die Anzeige, ohne `changed` auszulösen."""
        self._rgb = (int(r), int(g), int(b))
        self.update()

    def _disc(self) -> tuple[float, float, float]:
        w, h = self.width(), self.height()
        rad = max(10.0, min(w, h) / 2.0 - 6.0)
        return w / 2.0, h / 2.0, rad

    def _set_from_pos(self, px: float, py: float) -> None:
        cx, cy, rad = self._disc()
        self._rgb = rgb_from_xy((px - cx) / rad, (cy - py) / rad)
        self.update()
        self.changed.emit(*self._rgb)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            p = ev.position()
            self._set_from_pos(p.x(), p.y())

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag:
            p = ev.position()
            self._set_from_pos(p.x(), p.y())

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        self._drag = False

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        self._rgb = (0, 0, 0)
        self.update()
        self.changed.emit(0, 0, 0)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        cx, cy, rad = self._disc()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cone = QConicalGradient(QPointF(cx, cy), 0.0)       # Rot rechts, Grün oben links, Blau unten links
        for pos, col in ((0.0, "#ff0000"), (1 / 6, "#ffff00"), (2 / 6, "#00ff00"), (3 / 6, "#00ffff"),
                         (4 / 6, "#0000ff"), (5 / 6, "#ff00ff"), (1.0, "#ff0000")):
            cone.setColorAt(pos, QColor(col))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cone)
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        fade = QRadialGradient(QPointF(cx, cy), rad)         # Mitte = neutral grau
        fade.setColorAt(0.0, QColor(128, 128, 128, 255))
        fade.setColorAt(1.0, QColor(128, 128, 128, 0))
        p.setBrush(fade)
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#2c313d"), 1.5))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        x, y = xy_from_rgb(*self._rgb)
        mx, my = cx + x * rad, cy - y * rad
        p.setPen(QPen(QColor("black"), 3))
        p.drawEllipse(QPointF(mx, my), 6.0, 6.0)
        p.setPen(QPen(QColor("white"), 1.6))
        p.drawEllipse(QPointF(mx, my), 6.0, 6.0)
        p.end()


class CurveEditor(QWidget):
    """Gradationskurve für Helligkeit, Rot, Grün oder Blau. Klick = Punkt, Ziehen = verschieben, Rechtsklick = löschen."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._curves: dict[str, list[list[float]]] = {}
        self._ch = "m"
        self._drag = -1
        self.setMinimumSize(200, 200)
        self.setMouseTracking(False)
        self.setToolTip("Klick: Punkt setzen · Ziehen: verschieben · Rechtsklick oder Doppelklick auf Punkt: löschen")

    # ---- Daten
    def set_curves(self, curves: dict | None) -> None:
        """Setzt alle Kurven, ohne `changed` auszulösen."""
        self._curves = {ch: gradelib.normalize_points(pts) for ch, pts in (curves or {}).items()
                        if ch in gradelib.CURVE_CHANNELS}
        self.update()

    def curves(self) -> dict:
        """Nur die Kanäle, die wirklich etwas verändern."""
        return gradelib.clean_curves(self._curves)

    def set_channel(self, ch: str) -> None:
        if ch in gradelib.CURVE_CHANNELS:
            self._ch = ch
            self._drag = -1
            self.update()

    def channel(self) -> str:
        return self._ch

    def reset_channel(self) -> None:
        self._curves.pop(self._ch, None)
        self.update()
        self.changed.emit()

    def _pts(self) -> list[list[float]]:
        return self._curves.setdefault(self._ch, [[0.0, 0.0], [1.0, 1.0]])

    # ---- Umrechnung Bild ↔ Kurve
    def _box(self) -> QRectF:
        return QRectF(8.0, 8.0, max(20.0, self.width() - 16.0), max(20.0, self.height() - 16.0))

    def _to_curve(self, px: float, py: float) -> tuple[float, float]:
        b = self._box()
        return (px - b.left()) / b.width(), 1.0 - (py - b.top()) / b.height()

    def _to_px(self, x: float, y: float) -> QPointF:
        b = self._box()
        return QPointF(b.left() + x * b.width(), b.top() + (1.0 - y) * b.height())

    # ---- Maus
    def _hit(self, px: float, py: float) -> int:
        b = self._box()
        x, y = self._to_curve(px, py)
        return nearest_point(self._pts(), x, y, (POINT_RADIUS + 3.0) / b.width(), (POINT_RADIUS + 3.0) / b.height())

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        p = ev.position()
        hit = self._hit(p.x(), p.y())
        if ev.button() == Qt.MouseButton.RightButton:
            if hit >= 0 and remove_point(self._pts(), hit):
                self.update()
                self.changed.emit()
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if hit < 0:
            x, y = self._to_curve(p.x(), p.y())
            hit = add_point(self._pts(), x, y)
            if hit >= 0:
                self.changed.emit()
        self._drag = hit
        self.update()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag >= 0:
            p = ev.position()
            x, y = self._to_curve(p.x(), p.y())
            move_point(self._pts(), self._drag, x, y)
            self.update()
            self.changed.emit()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        self._drag = -1

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        p = ev.position()
        hit = self._hit(p.x(), p.y())
        if hit >= 0 and remove_point(self._pts(), hit):
            self._drag = -1
            self.update()
            self.changed.emit()

    # ---- Zeichnen
    def paintEvent(self, _ev) -> None:  # noqa: N802
        b = self._box()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0b0c0f"))
        p.setPen(QPen(QColor("#2c313d"), 1))
        for i in range(5):
            gx = b.left() + b.width() * i / 4.0
            gy = b.top() + b.height() * i / 4.0
            p.drawLine(QPointF(gx, b.top()), QPointF(gx, b.bottom()))
            p.drawLine(QPointF(b.left(), gy), QPointF(b.right(), gy))
        p.setPen(QPen(QColor(MUTED), 1, Qt.PenStyle.DashLine))
        p.drawLine(self._to_px(0, 0), self._to_px(1, 1))
        # inaktive Kanäle blass, der aktive kräftig
        for ch in gradelib.CURVE_CHANNELS:
            if ch == self._ch or ch not in self._curves or gradelib.curve_is_identity(self._curves[ch]):
                continue
            col = QColor(CHANNEL_COLORS[ch])
            col.setAlpha(90)
            self._draw_curve(p, self._curves[ch], col, 1.2)
        pts = self._pts()
        self._draw_curve(p, pts, QColor(CHANNEL_COLORS[self._ch]), 2.2)
        for i, (x, y) in enumerate(pts):
            c = self._to_px(x, y)
            p.setPen(QPen(QColor("black"), 3))
            p.setBrush(QColor(ACCENT if i == self._drag else CHANNEL_COLORS[self._ch]))
            p.drawEllipse(c, POINT_RADIUS - 1.5, POINT_RADIUS - 1.5)
        p.end()

    def _draw_curve(self, p: QPainter, pts, color: QColor, width: float) -> None:
        path = QPainterPath()
        first = True
        for x, y in spline(pts, 64):
            q = self._to_px(x, y)
            if first:
                path.moveTo(q)
                first = False
            else:
                path.lineTo(q)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, width))
        p.drawPath(path)
