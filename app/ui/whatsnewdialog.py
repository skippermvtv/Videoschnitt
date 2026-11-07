"""Fenster „Was ist neu“ (nach einem Update)."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout


class WhatsNewDialog(QDialog):
    def __init__(self, app_name: str, version: str, html_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{app_name} wurde aktualisiert")
        self.resize(680, 520)
        lay = QVBoxLayout(self)
        head = QLabel(f"<h2>{app_name} ist jetzt auf Version {version}</h2><p>Das hat sich geändert:</p>")
        lay.addWidget(head)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(html_text)
        lay.addWidget(self.browser, 1)
        self.off = QCheckBox("Dieses Fenster nach Updates nicht mehr anzeigen")
        lay.addWidget(self.off)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.buttons.accepted.connect(self.accept)
        lay.addWidget(self.buttons)
