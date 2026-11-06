"""Pipette: ein Standbild anzeigen, ein Klick wählt die Farbe (Mittelwert um den Klickpunkt)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from ..core import colorpick, maskgeom


class _Canvas(QWidget):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.image = image
        self.color = ""
        self.hover = ""
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.on_hover = None
        self.on_pick = None

    def _sample(self, ev) -> str:
        pos = colorpick.map_click(ev.position().x(), ev.position().y(), self.width(), self.height(),
                                  self.image.width(), self.image.height())
        if pos is None:
            return ""
        px = [self.image.pixelColor(x, y) for x, y in colorpick.neighborhood(pos[0], pos[1], self.image.width(), self.image.height())]
        return colorpick.average_hex([(c.red(), c.green(), c.blue()) for c in px])

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        self.hover = self._sample(ev)
        if self.on_hover:
            self.on_hover(self.hover)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        c = self._sample(ev)
        if c:
            self.color = c
            if self.on_pick:
                self.on_pick(c)
            self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))
        x, y, w, h = maskgeom.fit_rect(self.width(), self.height(), self.image.width(), self.image.height())
        p.drawImage(QRectF(x, y, w, h), self.image)
        p.end()


class PickDialog(QDialog):
    """Zeigt das Bild; `color` enthält nach „OK“ die gewählte Farbe („#rrggbb“), sonst leer."""

    def __init__(self, png_path: str, parent=None, title: str = "Farbe aus dem Bild wählen"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.color = ""
        img = QImage(png_path)
        lay = QVBoxLayout(self)
        hint = QLabel("Klicke im Bild auf die Hintergrundfarbe, die entfernt werden soll (z. B. die grüne Fläche).")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.canvas = _Canvas(img, self)
        lay.addWidget(self.canvas, 1)
        self.info = QLabel("Noch keine Farbe gewählt.")
        lay.addWidget(self.info)
        self.canvas.on_hover = lambda c: self.info.setText(f"Unter dem Zeiger: {c}" if c else "")
        self.canvas.on_pick = self._picked
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.resize(760, 520)

    def _picked(self, c: str) -> None:
        self.color = c
        self.info.setText(f"Gewählt: {c}")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
