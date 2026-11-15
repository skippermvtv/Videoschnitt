"""Fenster „Stapel-Export“: mehrere gespeicherte Projekte wählen, Formate und Zielordner festlegen."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from ..core import batch, presets


class BatchExportDialog(QDialog):
    def __init__(self, parent=None, start_files: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Stapel-Export")
        self.resize(560, 560)
        self.items: list[batch.Item] = []
        self.format_ids: list[str] = []
        self.folder = ""
        lay = QVBoxLayout(self)
        info = QLabel("Exportiert mehrere gespeicherte Projekte (.cforge) nacheinander, jedes in den angehakten Formaten. Die Projekte werden nicht "
                      "verändert. Projekte mit fehlenden Dateien oder ohne Clips werden übersprungen (mit Hinweis). Vorhandene Dateien werden nie "
                      "überschrieben. Der Export läuft im Vordergrund; plane bei vielen Projekten Zeit ein.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_add = QPushButton("Projekte hinzufügen …")
        b_dir = QPushButton("Ordner hinzufügen …")
        b_del = QPushButton("Entfernen")
        for b in (b_add, b_dir, b_del):
            row.addWidget(b)
        lay.addLayout(row)
        b_add.clicked.connect(lambda *_: self.add_files_dialog())
        b_dir.clicked.connect(lambda *_: self.add_folder_dialog())
        b_del.clicked.connect(lambda *_: self.remove_selected())
        lay.addWidget(QLabel("Formate:"))
        self.boxes: list[tuple[QCheckBox, str]] = []
        own = QCheckBox("Format wie im Projekt")
        own.setChecked(True)
        lay.addWidget(own)
        self.boxes.append((own, batch.OWN_FORMAT))
        for f in presets.load("formats"):
            cb = QCheckBox(f"{f['name']}  ({f['width']}×{f['height']})")
            lay.addWidget(cb)
            self.boxes.append((cb, f["id"]))
        form = QFormLayout()
        self.folder_edit = QLineEdit(str(Path.home() / "Videos" if (Path.home() / "Videos").is_dir() else Path.home()))
        pick = QPushButton("Ordner wählen …")
        pick.clicked.connect(lambda *_: self.folder_edit.setText(QFileDialog.getExistingDirectory(self, "Zielordner", self.folder_edit.text())
                                                                or self.folder_edit.text()))
        form.addRow("Zielordner", self.folder_edit)
        form.addRow(pick)
        lay.addLayout(form)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.buttons = QDialogButtonBox()
        self.btn_go = self.buttons.addButton("Exportieren", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for cb, _fid in self.boxes:
            cb.toggled.connect(self._update)
        if start_files:
            self.add_files(start_files)
        self._update()

    # -- Liste
    def add_files(self, files: list[str]) -> None:
        have = [i.file for i in self.items]
        self.items = batch.load_items(have + [f for f in files if f])
        self._fill()

    def add_files_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Projekte wählen", "", "FATE-Projekt (*.cforge)")
        if files:
            self.add_files(files)

    def add_folder_dialog(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Ordner mit Projekten")
        if d:
            found = batch.find_projects(d)
            if not found:
                self.summary.setText("In diesem Ordner liegen keine Projekte (.cforge).")
                return
            self.add_files(found)

    def remove_selected(self) -> None:
        rows = sorted({self.list.row(i) for i in self.list.selectedItems()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.items):
                del self.items[r]
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        for it in self.items:
            ok = not it.problem
            li = QListWidgetItem(("✓  " if ok else "⚠  ") + Path(it.file).name + ("" if ok else f"  –  {it.problem}"))
            li.setToolTip(it.file + ("" if ok else "\n" + it.problem))
            self.list.addItem(li)
        self._update()

    def _update(self, *_a) -> None:
        ready = sum(1 for i in self.items if not i.problem)
        fmts = sum(1 for cb, _f in self.boxes if cb.isChecked())
        self.btn_go.setEnabled(ready > 0 and fmts > 0)
        if not self.items:
            self.summary.setText("Noch keine Projekte gewählt.")
        else:
            skipped = len(self.items) - ready
            self.summary.setText(f"{ready} Projekt(e) bereit × {fmts} Format(e) = {ready * fmts} Datei(en)"
                                 + (f"; {skipped} wird/werden übersprungen." if skipped else "."))

    def accept(self) -> None:
        self.format_ids = [fid for cb, fid in self.boxes if cb.isChecked()]
        self.folder = self.folder_edit.text().strip()
        super().accept()
