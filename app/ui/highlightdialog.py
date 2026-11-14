"""Fenster „Highlights finden“: Länge und Anzahl wählen, analysieren, Vorschläge ansehen, als Marker setzen."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel, QListWidget, QPushButton, QSpinBox,
                               QVBoxLayout)

from ..core import highlights
from ..core.project import Project


class HighlightDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Highlights finden")
        self.resize(520, 420)
        self.project = project
        self.found: list[highlights.Highlight] = []
        lay = QVBoxLayout(self)
        intro = QLabel("Das Programm bewertet jeden Abschnitt nach Lautstärke, Sprechdichte und Schnitten und schlägt die besten vor "
                       "(z. B. für Shorts). Das ist eine Schätzung, kein Bildverständnis: bitte die Vorschläge selbst ansehen. "
                       "Mit „Als Marker setzen“ bekommt jeder Vorschlag einen Start- und Endmarker.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.spin_len = QSpinBox()
        self.spin_len.setRange(int(highlights.MIN_WINDOW), int(highlights.MAX_WINDOW))
        self.spin_len.setSuffix(" s")
        self.spin_len.setValue(30)
        self.spin_len.setToolTip("Länge jedes Vorschlags. Shorts/TikTok: 15–60 s.")
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 20)
        self.spin_count.setValue(5)
        form.addRow("Länge eines Abschnitts", self.spin_len)
        form.addRow("Anzahl Vorschläge", self.spin_count)
        lay.addLayout(form)
        self.btn_analyze = QPushButton("Analysieren")
        self.btn_analyze.clicked.connect(lambda *_: self.analyze())
        lay.addWidget(self.btn_analyze)
        self.result_list = QListWidget()
        lay.addWidget(self.result_list, 1)
        self.info = QLabel("Noch nicht analysiert.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.buttons = QDialogButtonBox()
        self.btn_apply = self.buttons.addButton("Als Marker setzen", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_apply.setEnabled(False)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.spin_len.valueChanged.connect(self._invalidate)
        self.spin_count.valueChanged.connect(self._invalidate)

    def _invalidate(self, *_a) -> None:
        self.found = []
        self.result_list.clear()
        self.btn_apply.setEnabled(False)
        self.info.setText("Werte geändert – bitte neu analysieren.")

    def analyze(self) -> bool:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.found = highlights.find(self.project, float(self.spin_len.value()), int(self.spin_count.value()))
        except highlights.HighlightError as exc:
            self.found = []
            self.result_list.clear()
            self.info.setText(str(exc))
            self.btn_apply.setEnabled(False)
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self.result_list.clear()
        for k, h in enumerate(self.found, 1):
            self.result_list.addItem(highlights.describe(h, k))
        self.info.setText(f"{len(self.found)} Vorschläge, nach Zeit sortiert.")
        self.btn_apply.setEnabled(bool(self.found))
        return True
