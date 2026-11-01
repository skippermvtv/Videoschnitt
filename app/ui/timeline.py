"""Einfache Timeline: zeigt die Clips als Blöcke (Breite = Länge), Klick wählt aus."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .theme import ACCENT, MUTED, PANEL

_COLORS = ["#3d5a80", "#5b7f5b", "#80603d", "#6b3d80", "#3d8080", "#80453d"]


class Timeline(QWidget):
    clip_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self._clips: list = []
        self._sel = -1
        self._rects: list[QRectF] = []

    def set_clips(self, clips, selected: int) -> None:
        self._clips = list(clips)
        self._sel = selected
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(PANEL))
        self._rects = []
        if not self._clips:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Noch keine Clips – links Dateien importieren und zur Timeline hinzufügen")
            return
        total = sum(c.length for c in self._clips) or 1.0
        left, top, bar_h = 12.0, 30.0, max(40.0, self.height() - 46.0)
        avail = max(50.0, self.width() - 24.0)
        gap = 3.0

        # Zeitlineal
        step = 1 if total <= 20 else 5 if total <= 100 else 15 if total <= 600 else 60
        p.setPen(QColor(MUTED))
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)
        t = 0.0
        while t <= total + 1e-6:
            x = left + t / total * avail
            p.drawLine(int(x), 18, int(x), 26)
            p.drawText(int(x) + 3, 14, f"{int(t // 60)}:{int(t % 60):02d}")
            t += step

        x = left
        for i, c in enumerate(self._clips):
            w = max(26.0, c.length / total * avail - gap)
            r = QRectF(x, top, w, bar_h)
            self._rects.append(r)
            p.setBrush(QColor(_COLORS[i % len(_COLORS)]))
            p.setPen(QPen(QColor(ACCENT), 3) if i == self._sel else Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor("white"))
            label = f"{c.name}\n{c.length:.1f} s" + (f"  ×{c.speed:g}" if abs(c.speed - 1) > 1e-3 else "")
            p.drawText(r.adjusted(6, 4, -6, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)
            x += w + gap

    def mousePressEvent(self, event):
        pos = event.position()
        for i, r in enumerate(self._rects):
            if r.contains(pos):
                self._sel = i
                self.clip_selected.emit(i)
                self.update()
                return
