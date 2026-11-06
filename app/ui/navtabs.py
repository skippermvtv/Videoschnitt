"""Reiterleiste im Stil von Filmora: Symbol über dem Namen, aktiver Reiter türkis unterstrichen.

Hat dieselben Aufrufe wie ein QTabWidget (addTab, setCurrentIndex, currentIndex, count, tabText, widget,
currentChanged), damit das Hauptfenster nur an einer Stelle ausgetauscht werden muss.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QScrollArea, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from .theme import ACCENT, LINE, MUTED, TEXT


class NavButton(QAbstractButton):
    def __init__(self, glyph: str, text: str, parent=None):
        super().__init__(parent)
        self._glyph = glyph
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        f = QFont(self.font())
        f.setPointSize(9)
        w = max(48, QFontMetrics(f).horizontalAdvance(self.text()) + 16)
        return QSize(w, 56)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isChecked()
        col = QColor(ACCENT if active else (TEXT if self.underMouse() else MUTED))
        w, h = float(self.width()), float(self.height())
        gf = QFont(self.font())
        gf.setPointSize(16)
        p.setFont(gf)
        p.setPen(col)
        p.drawText(QRectF(0, 3, w, 30), Qt.AlignmentFlag.AlignCenter, self._glyph)
        lf = QFont(self.font())
        lf.setPointSize(9)
        p.setFont(lf)
        p.drawText(QRectF(0, 33, w, 18), Qt.AlignmentFlag.AlignCenter, self.text())
        if active:
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawLine(int(w * 0.18), int(h) - 2, int(w * 0.82), int(h) - 2)
        p.end()


class _BarScroll(QScrollArea):
    """Seitlich verschiebbare Leiste ohne sichtbare Rollbalken (Mausrad schiebt)."""

    def wheelEvent(self, ev):  # noqa: N802
        d = ev.angleDelta().y() or ev.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - int(d / 120.0 * 90))
        ev.accept()


class NavTabs(QWidget):
    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: list[NavButton] = []
        self._pages: list[QWidget] = []
        self._labels: list[str] = []
        self._cur = -1
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._bar = QWidget()
        self._bar_lay = QHBoxLayout(self._bar)
        self._bar_lay.setContentsMargins(6, 0, 6, 0)
        self._bar_lay.setSpacing(2)
        self._bar_lay.addStretch(1)
        self._scroll = _BarScroll()
        self._scroll.setWidget(self._bar)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(58)
        self._scroll.setMinimumWidth(120)
        self._left = QToolButton()
        self._left.setText("‹")
        self._left.setAutoRaise(True)
        self._left.clicked.connect(lambda: self.scroll_by(-160))
        self._right = QToolButton()
        self._right.setText("›")
        self._right.setAutoRaise(True)
        self._right.clicked.connect(lambda: self.scroll_by(160))
        self._head = QHBoxLayout()
        self._head.setContentsMargins(0, 0, 0, 0)
        self._head.setSpacing(0)
        self._head.addWidget(self._left)
        self._head.addWidget(self._scroll, 1)
        self._head.addWidget(self._right)
        self._corner: QWidget | None = None
        root.addLayout(self._head)
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {LINE};")
        root.addWidget(line)
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

    def scroll_by(self, dx: int) -> None:
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() + dx)

    # --- QTabWidget-Schnittstelle
    def addTab(self, widget: QWidget, text: str, glyph: str = "") -> int:  # noqa: N802
        i = len(self._pages)
        btn = NavButton(glyph or text[:1], text)
        btn.clicked.connect(lambda *_a, k=i: self.setCurrentIndex(k))
        self._bar_lay.insertWidget(i, btn)
        self._buttons.append(btn)
        self._pages.append(widget)
        self._labels.append(text)
        self._stack.addWidget(widget)
        if self._cur < 0:
            self.setCurrentIndex(0)
        return i

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        if not 0 <= i < len(self._pages):
            return
        changed = i != self._cur
        self._cur = i
        for k, b in enumerate(self._buttons):
            was = b.blockSignals(True)
            b.setChecked(k == i)
            b.blockSignals(was)
            b.update()
        self._stack.setCurrentIndex(i)
        self._scroll.ensureWidgetVisible(self._buttons[i], 20, 0)
        if changed:
            self.currentChanged.emit(i)

    def currentIndex(self) -> int:  # noqa: N802
        return self._cur

    def count(self) -> int:
        return len(self._pages)

    def tabText(self, i: int) -> str:  # noqa: N802
        return self._labels[i] if 0 <= i < len(self._labels) else ""

    def widget(self, i: int) -> QWidget | None:
        return self._pages[i] if 0 <= i < len(self._pages) else None

    def setCornerWidget(self, w: QWidget) -> None:  # noqa: N802
        """Rechts neben der Reiterleiste, bleibt beim Verschieben stehen (z. B. der Export-Knopf)."""
        self._corner = w
        self._head.addWidget(w)
