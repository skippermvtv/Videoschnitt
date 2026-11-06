"""Zeichenfläche für die Geschwindigkeitskurve: Punkte ziehen, Doppelklick = Punkt hinzufügen, Rechtsklick = entfernen."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core import rampgraph
from .theme import ACCENT, LINE, MUTED, PANEL_2


class SpeedCurveEditor(QWidget):
    pointsChanged = Signal(list)          # nach jeder Änderung durch den Nutzer: [[Position %, Tempo], …]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pts: list[list[float]] = [[0.0, 1.0], [100.0, 1.0]]
        self._drag = -1
        self._hover = -1
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setToolTip("Punkte ziehen: Tempo (senkrecht, ×0,1 … ×8) und Stelle im Clip (waagerecht).\n"
                        "Doppelklick auf die Fläche: neuer Punkt. Rechtsklick auf einen Punkt: entfernen.")

    # --- Daten
    def points(self) -> list[list[float]]:
        return [list(p) for p in self._pts]

    def set_points(self, pts) -> None:
        """Von außen (Textfeld, Vorlage): setzt die Punkte, ohne ein Signal zu senden.
        Während des Ziehens (die Änderung kommt dann von hier selbst) wird nichts überschrieben."""
        if self._drag >= 0:
            return
        try:
            self._pts = [[float(p[0]), float(p[1])] for p in pts]
        except (TypeError, ValueError, IndexError):
            return
        if len(self._pts) < 2:
            self._pts = [[0.0, 1.0], [100.0, 1.0]]
        self._drag = self._hover = -1
        self.update()

    def _emit(self) -> None:
        self.pointsChanged.emit(rampgraph.rounded(self._pts))

    # --- Maus
    def _size(self) -> tuple[float, float]:
        return float(max(1, self.width())), float(max(1, self.height()))

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        w, h = self._size()
        i = rampgraph.hit(self._pts, ev.position().x(), ev.position().y(), w, h)
        if ev.button() == Qt.MouseButton.LeftButton and i >= 0:
            self._drag = i
        elif ev.button() == Qt.MouseButton.RightButton and i >= 0:
            new = rampgraph.remove(self._pts, i)
            if len(new) != len(self._pts):
                self._pts = new
                self._hover = -1
                self.update()
                self._emit()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        w, h = self._size()
        x, y = ev.position().x(), ev.position().y()
        if self._drag >= 0:
            pos, sp = rampgraph.from_px(x, y, w, h)
            self._pts = rampgraph.move(self._pts, self._drag, pos, sp)
            self.update()
            self._emit()
        else:
            i = rampgraph.hit(self._pts, x, y, w, h)
            if i != self._hover:
                self._hover = i
                self.update()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        self._drag = -1

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        w, h = self._size()
        pos, sp = rampgraph.from_px(ev.position().x(), ev.position().y(), w, h)
        new, i = rampgraph.add(self._pts, pos, sp)
        if i >= 0:
            self._pts = new
            self._hover = i
            self.update()
            self._emit()

    # --- Zeichnen
    def paintEvent(self, ev) -> None:  # noqa: N802
        w, h = self._size()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(PANEL_2))
        grid = QPen(QColor(LINE))
        for s in rampgraph.GRID_SPEEDS:
            y = (1.0 - rampgraph.speed_to_v(s)) * h
            grid.setWidthF(1.6 if s == 1.0 else 1.0)
            p.setPen(grid)
            p.drawLine(QPointF(0, y), QPointF(w, y))
            p.setPen(QColor(MUTED))
            p.drawText(QPointF(4, max(11.0, y - 2)), f"×{s:g}")
        p.setPen(grid)
        for k in range(1, 4):
            p.drawLine(QPointF(k * w / 4, 0), QPointF(k * w / 4, h))
        path = QPainterPath()
        for k, (x, y) in enumerate(rampgraph.polyline(self._pts, w, h)):
            path.moveTo(x, y) if k == 0 else path.lineTo(x, y)
        p.setPen(QPen(QColor(ACCENT), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        for i, pt in enumerate(self._pts):
            x, y = rampgraph.to_px(pt, w, h)
            on = i in (self._hover, self._drag)
            p.setPen(QPen(QColor("#07201c"), 1.5))
            p.setBrush(QColor("#ffffff") if on else QColor(ACCENT))
            p.drawEllipse(QPointF(x, y), 6.0 if on else 5.0, 6.0 if on else 5.0)
        p.end()
