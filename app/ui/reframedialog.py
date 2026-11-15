"""Fenster „Auto-Hochkant“: Clips fürs Hochformat so zuschneiden, dass der Ausschnitt dem Geschehen folgt."""
from __future__ import annotations

import copy

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout)

from ..core import reframe
from ..core.project import Project
from .workers import ReframeWorker

STYLE_LABELS = {"ruhig": "Ruhig (wenig Bewegung, bleibt lange stehen)", "normal": "Normal",
                "lebhaft": "Lebhaft (folgt schneller)"}


class ReframeDialog(QDialog):
    def __init__(self, project: Project, sel: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Hochkant (9:16)")
        self.resize(540, 420)
        self.project, self.sel = project, sel
        self.result: dict[int, list[dict]] = {}
        self.notes: list[str] = []
        self.set_fill = True
        self.set_format = False
        self.remove = False
        self._worker: ReframeWorker | None = None
        lay = QVBoxLayout(self)
        intro = QLabel("Querformat-Clips werden fürs Hochformat zugeschnitten. Das Programm schätzt je Bild, wo am meisten los ist (Bewegung und "
                       "Kontrast), und fährt den Ausschnitt ruhig dorthin. Es erkennt <b>keine Gesichter oder Personen</b>: bei ruhigen "
                       "Szenen, Bildschirmaufnahmen oder mehreren Personen bitte das Ergebnis ansehen. Die Original-Clips bleiben unverändert, "
                       "Strg+Z macht es rückgängig.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.cmb_scope = QComboBox()
        self.cmb_scope.addItem("Nur den gewählten Clip", "one")
        self.cmb_scope.addItem("Alle Clips", "all")
        has_sel = 0 <= sel < len(project.clips)
        if not has_sel:
            self.cmb_scope.setCurrentIndex(1)
            self.cmb_scope.model().item(0).setEnabled(False)
        elif len(project.clips) > 1:
            self.cmb_scope.setCurrentIndex(1)
        self.cmb_style = QComboBox()
        for key in reframe.STYLES:
            self.cmb_style.addItem(STYLE_LABELS[key], key)
        self.cmb_style.setCurrentIndex(self.cmb_style.findData(reframe.DEFAULT_STYLE))
        form.addRow("Für", self.cmb_scope)
        form.addRow("Kamerafahrt", self.cmb_style)
        lay.addLayout(form)
        self.chk_format = QCheckBox("Projektformat auf Shorts/TikTok (9:16) stellen")
        wide = reframe.target_aspect(project) > 0.8
        self.chk_format.setVisible(wide)
        self.chk_format.setChecked(wide)
        self.chk_fill = QCheckBox("Anpassung „Füllen“ verwenden (nötig, damit der Ausschnitt wirkt)")
        self.chk_fill.setChecked(True)
        lay.addWidget(self.chk_format)
        lay.addWidget(self.chk_fill)
        self.btn_analyze = QPushButton("Analysieren")
        self.btn_analyze.clicked.connect(lambda *_: self.analyze())
        lay.addWidget(self.btn_analyze)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.info = QLabel("Noch nicht analysiert.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info, 1)
        self.buttons = QDialogButtonBox()
        self.btn_apply = self.buttons.addButton("Übernehmen", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_apply.setEnabled(False)
        self.btn_remove = self.buttons.addButton("Auto-Hochkant entfernen", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.btn_remove.clicked.connect(self._on_remove)
        lay.addWidget(self.buttons)
        for w in (self.cmb_scope, self.cmb_style):
            w.currentIndexChanged.connect(self._invalidate)
        self.chk_format.toggled.connect(self._invalidate)

    def indices(self) -> list[int]:
        if self.cmb_scope.currentData() == "one" and 0 <= self.sel < len(self.project.clips):
            return [self.sel]
        return list(range(len(self.project.clips)))

    def _invalidate(self, *_a) -> None:
        if self._worker is not None:
            return
        self.result, self.notes = {}, []
        self.btn_apply.setEnabled(False)
        self.info.setText("Werte geändert – bitte neu analysieren.")

    def _analysis_project(self) -> Project:
        p = copy.deepcopy(self.project)
        if self.chk_format.isVisible() and self.chk_format.isChecked():
            p.format_id = "shorts"
        return p

    def analyze(self) -> None:
        if self._worker is not None:
            return
        idx = self.indices()
        self.btn_analyze.setEnabled(False)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.info.setText("Analysiere … (je Clip etwa 1–10 Sekunden)")
        self._worker = ReframeWorker(self._analysis_project(), idx, str(self.cmb_style.currentData()), self)
        self._worker.progress.connect(lambda p: self.bar.setValue(int(p * 100)))
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, res, notes, err: str) -> None:
        w, self._worker = self._worker, None
        if w is not None:
            w.wait(3000)
        self.bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        if err:
            self.info.setText("Fehler: " + err if err != "abgebrochen" else "Abgebrochen.")
            return
        self.result, self.notes = res or {}, list(notes or [])
        moving = sum(1 for k in self.result.values() if k)
        centred = len(self.result) - moving
        text = f"{moving} Clip(s) mit Kamerafahrt"
        if centred:
            text += f", {centred} Clip(s) bleiben in der Mitte (dort passiert seitlich nichts)"
        text += "."
        if self.notes:
            text += "\n\nÜbersprungen:\n" + "\n".join(self.notes)
        self.info.setText(text)
        self.btn_apply.setEnabled(bool(self.result))

    def reject(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(5000)
            self._worker = None
        super().reject()

    def _on_remove(self, *_a) -> None:
        self.remove = True
        self.result = {i: [] for i in self.indices()}
        super().accept()

    def accept(self) -> None:
        if self._worker is not None:
            return
        self.set_fill = self.chk_fill.isChecked()
        self.set_format = self.chk_format.isVisible() and self.chk_format.isChecked()
        super().accept()
