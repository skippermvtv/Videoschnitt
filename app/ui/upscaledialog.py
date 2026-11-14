"""Fenster „KI-Hochskalieren“: Ziel und Modell wählen, ehrliche Hinweise zu Dauer und Ergebnis."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from ..core import upscale
from ..core.project import Clip


class UpscaleDialog(QDialog):
    def __init__(self, clip: Clip, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KI-Hochskalieren")
        self.clip = clip
        self.target = 0
        self.model_key = "video"
        self.test_only = False
        lay = QVBoxLayout(self)
        seg = max(0.0, (clip.out_pt if clip.out_pt > clip.in_pt else clip.duration) - clip.in_pt)
        intro = QLabel(f"Der Clip ({clip.width}×{clip.height}, {seg:.0f} s) wird mit Real-ESRGAN (neuronales Netz, läuft auf deiner Grafikkarte) "
                       "größer gerechnet. Das ist <b>keine verlustfreie</b> Vergrößerung: Das Modell erfindet Details dazu. Meist sieht es "
                       "schärfer aus als normales Hochrechnen, bei Gesichtern und Schrift kann es aber künstlich wirken. Das Ergebnis ist eine "
                       "neue Datei, der Clip zeigt danach darauf (Strg+Z macht es rückgängig).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.cmb_target = QComboBox()
        for h, label in upscale.TARGETS.items():
            if h > clip.height > 0:
                self.cmb_target.addItem(label, h)
        self.cmb_model = QComboBox()
        for key, (_name, _scales, desc) in upscale.MODELS.items():
            self.cmb_model.addItem(desc, key)
        self.chk_test = QCheckBox("Nur die ersten 10 Sekunden zum Test (wird als neuer Clip dahinter eingefügt)")
        self.chk_test.setChecked(seg > 30)
        form.addRow("Ziel", self.cmb_target)
        form.addRow("Modell", self.cmb_model)
        form.addRow(self.chk_test)
        lay.addLayout(form)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.buttons = QDialogButtonBox()
        self.btn_go = self.buttons.addButton("Starten", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.chk_test.toggled.connect(self._update)
        self.cmb_model.currentIndexChanged.connect(self._update)
        self._update()

    def _update(self, *_a) -> None:
        seg = max(0.0, (self.clip.out_pt if self.clip.out_pt > self.clip.in_pt else self.clip.duration) - self.clip.in_pt)
        secs = min(seg, 10.0) if self.chk_test.isChecked() else seg
        frames = int(secs * 30)
        ok = self.cmb_target.count() > 0
        self.btn_go.setEnabled(ok)
        if not ok:
            self.note.setText("Der Clip ist schon mindestens 2K groß – hochskalieren ist nicht nötig.")
            return
        self.note.setText(f"Etwa {frames} Bilder bei 30 fps. Jedes Bild geht einzeln durch die Grafikkarte; nach dem ersten Stück zeigt das "
                          "Programm eine Schätzung der Restzeit. Plane bei längeren Clips Stunden ein und teste zuerst die 10 Sekunden. "
                          "Es braucht mindestens 4 GB freien Platz (Zwischenstücke werden laufend gelöscht), die neue Datei ist groß.")

    def accept(self) -> None:
        self.target = int(self.cmb_target.currentData() or 0)
        self.model_key = str(self.cmb_model.currentData() or "video")
        self.test_only = self.chk_test.isChecked()
        super().accept()
