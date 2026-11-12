"""Fenster „Stille entfernen“: Analyse, Zahlen als Vorschau, Anwenden."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QPushButton,
                               QVBoxLayout)

from ..core import silence
from ..core.project import Clip


class SilenceDialog(QDialog):
    def __init__(self, clip: Clip, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stille entfernen")
        self.clip = clip
        self.silences: list[tuple[float, float]] | None = None
        self.cuts: list[tuple[float, float]] = []
        lay = QVBoxLayout(self)
        intro = QLabel("Das Programm sucht die Pausen im Ton des Clips und schneidet sie heraus. Erst „Analysieren“, dann siehst du "
                       "die Zahlen; geändert wird der Clip erst mit „Anwenden“ (Strg+Z macht es rückgängig).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.spin_db = QDoubleSpinBox()
        self.spin_db.setRange(-70.0, -10.0)
        self.spin_db.setSingleStep(1.0)
        self.spin_db.setDecimals(0)
        self.spin_db.setSuffix(" dB")
        self.spin_db.setValue(silence.DEFAULT_DB)
        self.spin_db.setToolTip("Leiser als dieser Wert gilt als Stille. Näher an 0 dB = mehr wird als Pause erkannt.")
        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(0.1, 10.0)
        self.spin_min.setSingleStep(0.1)
        self.spin_min.setSuffix(" s")
        self.spin_min.setValue(silence.DEFAULT_MIN)
        self.spin_min.setToolTip("Nur Pausen, die mindestens so lang sind, werden geschnitten.")
        self.spin_pad = QDoubleSpinBox()
        self.spin_pad.setRange(0.0, 1.0)
        self.spin_pad.setSingleStep(0.02)
        self.spin_pad.setSuffix(" s")
        self.spin_pad.setValue(silence.DEFAULT_PAD)
        self.spin_pad.setToolTip("So viel Pause bleibt vor und nach dem Gesprochenen stehen, damit nichts abgeschnitten klingt.")
        form.addRow("Leiser als", self.spin_db)
        form.addRow("Pause mindestens", self.spin_min)
        form.addRow("Rand behalten", self.spin_pad)
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
        self.spin_pad.valueChanged.connect(self._recalc)
        self.spin_db.valueChanged.connect(self._invalidate)
        self.spin_min.valueChanged.connect(self._invalidate)

    def _invalidate(self, *_a) -> None:
        """dB und Mindestlänge ändern die Analyse: neu analysieren."""
        self.silences = None
        self.cuts = []
        self.btn_apply.setEnabled(False)
        self.info.setText("Werte geändert – bitte neu analysieren.")

    def analyze(self) -> bool:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.silences = silence.detect(self.clip, self.spin_db.value(), self.spin_min.value())
        except silence.SilenceError as exc:
            self.silences = None
            self.info.setText(str(exc))
            self.btn_apply.setEnabled(False)
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self._recalc()
        return True

    def _recalc(self, *_a) -> None:
        if self.silences is None:
            return
        self.cuts = silence.cuts_from(self.silences, self.clip.in_pt, self.clip.out_pt, self.spin_pad.value())
        s = silence.summary(self.cuts, self.clip.in_pt, self.clip.out_pt, self.clip.speed)
        self.info.setText(silence.describe(s))
        self.btn_apply.setEnabled(bool(self.cuts))
