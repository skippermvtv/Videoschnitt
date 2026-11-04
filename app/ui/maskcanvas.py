"""Standbild mit ziehbarem Masken-Rahmen (ersetzt beim Bearbeiten kurz den Player)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..core import maskgeom
from .theme import ACCENT

_CURSORS = {"size_fdiag": Qt.CursorShape.SizeFDiagCursor, "size_bdiag": Qt.CursorShape.SizeBDiagCursor,
            "size_hor": Qt.CursorShape.SizeHorCursor, "size_ver": Qt.CursorShape.SizeVerCursor,
            "size_all": Qt.CursorShape.SizeAllCursor, "arrow": Qt.CursorShape.ArrowCursor}


class MaskCanvas(QWidget):
    changed = Signal(dict)          # neue Maske (x, y, w, h in %), wird beim Ziehen laufend gesendet

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._mask: dict | None = None
        self._track: list = []
        self._mode: str | None = None
        self._start_pos = QPointF()
        self._start_mask: dict | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background: black;")

    # ---- Daten
    def set_frame(self, png_path: str) -> bool:
        pm = QPixmap(png_path)
        self._pix = None if pm.isNull() else pm
        self.update()
        return self._pix is not None

    def clear_frame(self) -> None:
        self._pix = None
        self._mask = None
        self._track = []
        self.update()

    def has_frame(self) -> bool:
        return self._pix is not None

    def set_mask(self, mask: dict | None, track: list | None = None) -> None:
        self._mask = dict(mask) if mask else None
        self._track = list(track or [])
        self.update()

    def mask(self) -> dict | None:
        return dict(self._mask) if self._mask else None

    # ---- Geometrie
    def _img_rect(self) -> QRectF:
        if self._pix is None:
            return QRectF(0, 0, self.width(), self.height())
        x, y, w, h = maskgeom.fit_rect(self.width(), self.height(), self._pix.width(), self._pix.height())
        return QRectF(x, y, w, h)

    def _to_img(self, pos: QPointF) -> tuple[float, float, QRectF]:
        r = self._img_rect()
        return pos.x() - r.x(), pos.y() - r.y(), r

    # ---- Zeichnen
    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("black"))
        r = self._img_rect()
        if self._pix is not None:
            p.drawPixmap(r.toRect(), self._pix)
        else:
            p.setPen(QColor("#8d929d"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Bild wird geladen …")
            p.end()
            return
        m = self._mask
        if not m:
            p.end()
            return
        l, t, rr, b = maskgeom.box(m)
        shape = QRectF(r.x() + l / 100 * r.width(), r.y() + t / 100 * r.height(),
                       (rr - l) / 100 * r.width(), (b - t) / 100 * r.height())
        # außerhalb der Form abdunkeln (nur zur Orientierung)
        path = QPainterPath()
        path.addRect(r)
        inner = QPainterPath()
        if m.get("shape") == "rect":
            inner.addRect(shape)
        else:
            inner.addEllipse(shape)
        p.setClipRect(r)
        p.fillPath(path.subtracted(inner), QColor(0, 0, 0, 110))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawPath(inner)
        p.setPen(QPen(QColor(ACCENT), 1, Qt.PenStyle.DashLine))
        p.drawRect(shape)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT))
        for hx, hy in ((shape.left(), shape.top()), (shape.center().x(), shape.top()), (shape.right(), shape.top()),
                       (shape.left(), shape.center().y()), (shape.right(), shape.center().y()),
                       (shape.left(), shape.bottom()), (shape.center().x(), shape.bottom()), (shape.right(), shape.bottom())):
            p.drawRect(QRectF(hx - 4, hy - 4, 8, 8))
        if len(self._track) >= 2:
            p.setPen(QPen(QColor("#ffd24a"), 2))
            pts = [QPointF(r.x() + q[1] / 100 * r.width(), r.y() + q[2] / 100 * r.height()) for q in self._track]
            for a, c in zip(pts, pts[1:]):
                p.drawLine(a, c)
        p.end()

    # ---- Maus
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton or not self._mask or self._pix is None:
            return
        x, y, r = self._to_img(ev.position())
        self._mode = maskgeom.hit(self._mask, r.width(), r.height(), x, y)
        self._start_pos = ev.position()
        self._start_mask = dict(self._mask)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if not self._mask or self._pix is None:
            return
        r = self._img_rect()
        if self._mode and self._start_mask is not None:          # _mode ist nur zwischen Drücken und Loslassen gesetzt
            dx = (ev.position().x() - self._start_pos.x()) / max(r.width(), 1.0) * 100.0
            dy = (ev.position().y() - self._start_pos.y()) / max(r.height(), 1.0) * 100.0
            self._mask = maskgeom.drag(self._start_mask, self._mode, dx, dy)
            self.update()
            self.changed.emit(dict(self._mask))
            return
        x, y, r = self._to_img(ev.position())
        self.setCursor(QCursor(_CURSORS.get(maskgeom.cursor_name(maskgeom.hit(self._mask, r.width(), r.height(), x, y)),
                                            Qt.CursorShape.ArrowCursor)))

    def mouseReleaseEvent(self, _ev) -> None:  # noqa: N802
        self._mode = None
        self._start_mask = None
