"""Fenster „An Szenenwechseln teilen“: Analyse, Zahlen als Vorschau, Anwenden."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QPushButton,
                               QVBoxLayout)

from ..core import scenes
from ..core.project import Clip


class SceneDialog(QDialog):
    def __init__(self, clip: Clip, parent=None):
        super().__init__(parent)
        self.setWindowTitle("An Szenenwechseln teilen")
        self.clip = clip
        self.times: list[float] | None = None
        self.cuts: list[float] = []
        lay = QVBoxLayout(self)
        intro = QLabel("Das Programm sucht Stellen, an denen sich das Bild stark ändert (Schnitte im Material), und teilt den Clip "
                       "dort. Erst „Analysieren“; geändert wird der Clip erst mit „Anwenden“ (Strg+Z macht es rückgängig).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.spin_thr = QDoubleSpinBox()
        self.spin_thr.setRange(0.05, 0.95)
        self.spin_thr.setSingleStep(0.05)
        self.spin_thr.setDecimals(2)
        self.spin_thr.setValue(scenes.DEFAULT_THRESHOLD)
        self.spin_thr.setToolTip("Niedriger = auch sanfte Wechsel werden erkannt. Höher = nur sehr deutliche Schnitte.")
        self.spin_len = QDoubleSpinBox()
        self.spin_len.setRange(0.1, 30.0)
        self.spin_len.setSingleStep(0.1)
        self.spin_len.setSuffix(" s")
        self.spin_len.setValue(scenes.DEFAULT_MIN_LEN)
        self.spin_len.setToolTip("Kürzere Szenen werden nicht gebildet.")
        form.addRow("Schwelle", self.spin_thr)
        form.addRow("Szene mindestens", self.spin_len)
        lay.addLayout(form)
        self.btn_analyze = QPushButton("Analysieren")
        self.btn_analyze.clicked.connect(lambda *_: self.analyze())
        lay.addWidget(self.btn_analyze)
        self.info = QLabel("Noch nicht analysiert.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.buttons = QDialogButtonBox()
        self.btn_apply = self.buttons.addButton("Anwenden", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_apply.setEnabled(False)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.spin_len.valueChanged.connect(self._recalc)
        self.spin_thr.valueChanged.connect(self._invalidate)

    def _invalidate(self, *_a) -> None:
        self.times = None
        self.cuts = []
        self.btn_apply.setEnabled(False)
        self.info.setText("Schwelle geändert – bitte neu analysieren.")

    def analyze(self) -> bool:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.times = scenes.detect(self.clip, self.spin_thr.value())
        except scenes.SceneError as exc:
            self.times = None
            self.info.setText(str(exc))
            self.btn_apply.setEnabled(False)
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self._recalc()
        return True

    def _recalc(self, *_a) -> None:
        if self.times is None:
            return
        self.cuts = scenes.cuts_from(self.times, self.clip.in_pt, self.clip.out_pt, self.spin_len.value())
        self.info.setText(scenes.describe(self.cuts, self.clip.in_pt, self.clip.out_pt))
        self.btn_apply.setEnabled(bool(self.cuts))
