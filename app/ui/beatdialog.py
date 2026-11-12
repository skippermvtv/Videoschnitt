"""Fenster „Beats erkennen“: Tempo anzeigen, Marker setzen und/oder Clips auf den Beat schneiden."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton,
                               QVBoxLayout)

from ..core import beats
from ..core.project import AudioClip

STEPS = ((1, "Jeder Beat"), (2, "Jeder 2. Beat"), (4, "Jeder 4. Beat (ein Takt)"))


class BeatDialog(QDialog):
    def __init__(self, clip: AudioClip, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Beats erkennen")
        self.clip = clip
        self.result: beats.BeatResult | None = None
        self.times: list[float] = []
        lay = QVBoxLayout(self)
        intro = QLabel("Das Programm sucht den Takt in der Musik des gewählten Audioblocks. Danach kannst du Marker auf die Schläge setzen "
                       "und/oder die Schnitte zwischen deinen Clips auf die Beats legen. Erst „Analysieren“, geändert wird erst mit "
                       "„Anwenden“ (Strg+Z macht es rückgängig).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.cmb_step = QComboBox()
        for n, label in STEPS:
            self.cmb_step.addItem(label, n)
        self.cmb_step.currentIndexChanged.connect(self._recalc)
        form.addRow("Welche Schläge", self.cmb_step)
        lay.addLayout(form)
        self.chk_markers = QCheckBox("Marker auf die Schläge setzen")
        self.chk_markers.setChecked(True)
        self.chk_cut = QCheckBox("Clips auf diese Schläge schneiden (Länge der Clips wird angepasst)")
        self.chk_markers.toggled.connect(self._recalc)
        self.chk_cut.toggled.connect(self._recalc)
        lay.addWidget(self.chk_markers)
        lay.addWidget(self.chk_cut)
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

    @property
    def step(self) -> int:
        return int(self.cmb_step.currentData() or 1)

    @property
    def want_markers(self) -> bool:
        return self.chk_markers.isChecked()

    @property
    def want_cut(self) -> bool:
        return self.chk_cut.isChecked()

    def analyze(self) -> bool:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.result = beats.analyze_audio(self.clip)
        except beats.BeatError as exc:
            self.result = None
            self.info.setText(str(exc))
            self.btn_apply.setEnabled(False)
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self._recalc()
        return True

    def _recalc(self, *_a) -> None:
        if self.result is None:
            return
        self.times = beats.to_project_times(self.clip, self.result, self.step)
        self.info.setText(beats.describe(self.result, self.step))
        self.btn_apply.setEnabled(bool(self.times) and (self.want_markers or self.want_cut))
