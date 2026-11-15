"""Fenster „Marken-Vorlage“: Intro, Outro und Logo festlegen, speichern und in das Projekt einsetzen."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ..core import brand

MEDIA_FILTER = ("Videos und Bilder (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.mts *.m2ts *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;"
                "Alle Dateien (*)")
LOGO_FILTER = "Bilder (*.png *.jpg *.jpeg *.webp *.bmp);;Alle Dateien (*)"
CORNER_LABELS = {"tl": "Oben links", "tr": "Oben rechts", "bl": "Unten links", "br": "Unten rechts"}


class _PathRow(QWidget):
    def __init__(self, title: str, filt: str, parent=None):
        super().__init__(parent)
        self._title, self._filter = title, filt
        self.path = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("–")
        self.label.setMinimumWidth(180)
        pick = QPushButton("Wählen …")
        clear = QPushButton("Leeren")
        lay.addWidget(self.label, 1)
        lay.addWidget(pick)
        lay.addWidget(clear)
        pick.clicked.connect(lambda *_: self.pick())
        clear.clicked.connect(lambda *_: self.set_path(""))

    def set_path(self, p: str) -> None:
        self.path = p or ""
        self.label.setText(Path(p).name if p else "–")
        self.label.setToolTip(p or "")

    def pick(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, self._title, str(Path(self.path).parent) if self.path else "", self._filter)
        if f:
            self.set_path(f)


class BrandDialog(QDialog):
    """`action` nach dem Schließen: "save" | "apply" | "remove" (oder leer bei Abbrechen)."""

    def __init__(self, kit: brand.Kit, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Marken-Vorlage (Intro, Outro, Logo)")
        self.resize(560, 420)
        self.action = ""
        lay = QVBoxLayout(self)
        info = QLabel("Lege einmal dein Intro, Outro und Logo fest. „Einsetzen“ setzt sie in das aktuelle Projekt: das Intro an den Anfang, das Outro "
                      "ans Ende, das Logo über das ganze Video. Alles andere auf der Timeline rückt passend mit. Erneutes Einsetzen ersetzt die "
                      "Markenclips (nichts doppelt). Intro und Outro sind normale Clips, du kannst sie danach wie jeden anderen Clip kürzen "
                      "oder ändern.")
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.row_intro = _PathRow("Intro wählen", MEDIA_FILTER)
        self.row_outro = _PathRow("Outro wählen", MEDIA_FILTER)
        self.row_logo = _PathRow("Logo wählen", LOGO_FILTER)
        self.spin_img = QDoubleSpinBox()
        self.spin_img.setRange(brand.MIN_IMAGE_SECONDS, brand.MAX_IMAGE_SECONDS)
        self.spin_img.setSingleStep(0.5)
        self.spin_img.setSuffix(" s")
        self.cmb_corner = QComboBox()
        for k in brand.CORNERS:
            self.cmb_corner.addItem(CORNER_LABELS[k], k)
        self.spin_size = QDoubleSpinBox()
        self.spin_size.setRange(2, 60)
        self.spin_size.setSuffix(" % der Bildbreite")
        self.spin_op = QDoubleSpinBox()
        self.spin_op.setRange(0, 100)
        self.spin_op.setSuffix(" %")
        form.addRow("Intro (Video oder Bild)", self.row_intro)
        form.addRow("Outro (Video oder Bild)", self.row_outro)
        form.addRow("Bild als Intro/Outro zeigen", self.spin_img)
        form.addRow("Logo (Wasserzeichen)", self.row_logo)
        form.addRow("Logo-Ecke", self.cmb_corner)
        form.addRow("Logo-Größe", self.spin_size)
        form.addRow("Logo-Deckkraft", self.spin_op)
        lay.addLayout(form)
        self.chk_auto = QCheckBox("Automatisch einsetzen, sobald der erste Clip in ein leeres Projekt kommt")
        lay.addWidget(self.chk_auto)
        lay.addStretch(1)
        self.buttons = QDialogButtonBox()
        self.btn_apply = self.buttons.addButton("Speichern und einsetzen", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_save = self.buttons.addButton("Nur speichern", QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_remove = self.buttons.addButton("Aus Projekt entfernen", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self.reject)
        self.btn_apply.clicked.connect(lambda *_: self._finish("apply"))
        self.btn_save.clicked.connect(lambda *_: self._finish("save"))
        self.btn_remove.clicked.connect(lambda *_: self._finish("remove"))
        lay.addWidget(self.buttons)
        self.set_kit(kit)

    def set_kit(self, kit: brand.Kit) -> None:
        self.row_intro.set_path(kit.intro)
        self.row_outro.set_path(kit.outro)
        self.row_logo.set_path(kit.logo)
        self.spin_img.setValue(kit.image_seconds)
        self.cmb_corner.setCurrentIndex(max(0, self.cmb_corner.findData(kit.corner)))
        self.spin_size.setValue(kit.size)
        self.spin_op.setValue(kit.opacity)
        self.chk_auto.setChecked(kit.auto_new)

    def kit(self) -> brand.Kit:
        return brand.clean(brand.Kit(intro=self.row_intro.path, outro=self.row_outro.path, image_seconds=self.spin_img.value(),
                                     logo=self.row_logo.path, corner=str(self.cmb_corner.currentData()), size=self.spin_size.value(),
                                     opacity=self.spin_op.value(), auto_new=self.chk_auto.isChecked()))

    def _finish(self, action: str) -> None:
        self.action = action
        self.accept()
