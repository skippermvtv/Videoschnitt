"""Fenster „Text-Schnitt“: Füllwörter, Wiederholungen und Pausen aus den Wortzeiten der Untertitel entfernen,
dazu einzelne Wörter von Hand wählen. Erst Vorschau (Liste mit Häkchen), geändert wird erst mit „Anwenden“."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

from ..core import textcut
from ..core.project import Project


def stamp(t: float) -> str:
    m, s = divmod(max(0.0, t), 60.0)
    return f"{int(m)}:{s:04.1f}"


class TextCutDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Text-Schnitt")
        self.resize(620, 640)
        self.project = project
        self.words = textcut.words_of(project)
        self.manual: list[textcut.Cut] = []
        self.shown: list[textcut.Cut] = []
        self.cuts: list[textcut.Cut] = []
        lay = QVBoxLayout(self)
        intro = QLabel("Schneidet nach dem gesprochenen Text: Füllwörter („ähm“), doppelte Wörter und Pausen. Du siehst zuerst die Liste "
                       "der Schnitte und kannst einzelne abwählen. Geändert wird erst mit „Anwenden“ (Strg+Z macht es rückgängig). "
                       "Untertitel rücken mit. Bild-in-Bild und Ton-Blöcke auf eigenen Spuren bleiben an ihrer Zeit.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.chk_fill = QCheckBox("Füllwörter entfernen (ähm, äh, hm …)")
        self.chk_fill.setChecked(True)
        self.chk_rep = QCheckBox("Doppelte Wörter entfernen („ich ich denke“)")
        self.chk_rep.setChecked(True)
        self.chk_pause = QCheckBox("Pausen zwischen Wörtern kürzen, länger als")
        self.spin_pause = QDoubleSpinBox()
        self.spin_pause.setRange(0.2, 3.0)
        self.spin_pause.setSingleStep(0.1)
        self.spin_pause.setSuffix(" s")
        self.spin_pause.setValue(textcut.DEFAULT_PAUSE)
        self.spin_pause.setToolTip("Eine Pause wird bis auf einen kurzen Rand herausgeschnitten. Lücken über 4 s bleiben stehen (meist Absicht).")
        row = QHBoxLayout()
        row.addWidget(self.chk_pause)
        row.addWidget(self.spin_pause)
        row.addStretch(1)
        lay.addWidget(self.chk_fill)
        lay.addWidget(self.chk_rep)
        lay.addLayout(row)
        lay.addWidget(QLabel("Transkript: Wörter markieren (Strg/Umschalt für mehrere) und zur Liste hinzufügen"))
        self.word_list = QListWidget()
        self.word_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for w in self.words:
            self.word_list.addItem(f"{stamp(w.start)}   {w.text}")
        lay.addWidget(self.word_list, 2)
        self.btn_add = QPushButton("Markierte Wörter zur Schnittliste hinzufügen")
        self.btn_add.clicked.connect(lambda *_: self.add_selected())
        lay.addWidget(self.btn_add)
        lay.addWidget(QLabel("Schnittliste (Häkchen = wird geschnitten)"))
        self.cut_list = QListWidget()
        lay.addWidget(self.cut_list, 3)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.buttons = QDialogButtonBox()
        self.btn_apply = self.buttons.addButton("Anwenden", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for w in (self.chk_fill, self.chk_rep, self.chk_pause):
            w.toggled.connect(self.rebuild)
        self.spin_pause.valueChanged.connect(self.rebuild)
        self.cut_list.itemChanged.connect(self._update_info)
        self.rebuild()

    def auto_cuts(self) -> list[textcut.Cut]:
        return textcut.suggest(self.words, self.chk_fill.isChecked(), self.chk_rep.isChecked(),
                               self.spin_pause.value() if self.chk_pause.isChecked() else 0.0)

    def rebuild(self, *_a) -> None:
        """Liste neu aufbauen: automatische Vorschläge plus von Hand hinzugefügte Schnitte."""
        self.shown = textcut.merge(self.auto_cuts() + self.manual)
        was = self.cut_list.blockSignals(True)
        self.cut_list.clear()
        for c in self.shown:
            it = QListWidgetItem(f"{stamp(c.start)}   {c.kind}   „{c.label}“   ({c.length:.1f} s)")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.cut_list.addItem(it)
        self.cut_list.blockSignals(was)
        self._update_info()

    def add_selected(self) -> int:
        idx = sorted(self.word_list.row(i) for i in self.word_list.selectedItems())
        picked = [self.words[i] for i in idx if 0 <= i < len(self.words)]
        if not picked:
            self.info.setText("Zuerst im Transkript Wörter markieren.")
            return 0
        self.manual = textcut.merge(self.manual + textcut.from_words(picked))
        self.rebuild()
        return len(picked)

    def checked_cuts(self) -> list[textcut.Cut]:
        out = []
        for i, c in enumerate(self.shown):
            it = self.cut_list.item(i)
            if it is not None and it.checkState() == Qt.CheckState.Checked:
                out.append(c)
        return out

    def _update_info(self, *_a) -> None:
        cuts = self.checked_cuts()
        self.info.setText(textcut.describe(cuts) if self.words else "Keine Wortzeiten vorhanden.")
        self.btn_apply.setEnabled(bool(cuts))

    def accept(self) -> None:
        self.cuts = self.checked_cuts()
        super().accept()
