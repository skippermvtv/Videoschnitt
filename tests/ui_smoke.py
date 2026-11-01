"""Echter Start-Test mit PySide6 (läuft ohne Bildschirm: QT_QPA_PLATFORM=offscreen).

Startet das Hauptfenster, prüft die Presets, wählt einen Look, legt einen Text an und
speichert einen Screenshot. Läuft automatisch im GitHub-Workflow vor dem Bauen.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.theme import STYLE  # noqa: E402


def main() -> int:
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.resize(1480, 880)
    win.show()
    app.processEvents()

    assert win.cmb_format.count() >= 7, "Format-Presets fehlen"
    assert win.cmb_export.count() >= 4, "Export-Presets fehlen"
    assert win.cmb_look.count() >= 8, "Looks fehlen"
    assert win.fx_tree.topLevelItemCount() >= 4, "Effekt-Kategorien fehlen"

    win.cmb_look.setCurrentIndex(win.cmb_look.findData("glitch_intro"))
    win._on_look_chosen(0)
    assert any(e["id"] == "glitch" for e in win.project.effects), "Look wurde nicht angewendet"

    win.cmb_format.setCurrentIndex(win.cmb_format.findData("tiktok"))
    assert win.project.format_id == "tiktok"

    win.tabs.setCurrentIndex(2)
    win.add_text()
    assert len(win.project.texts) == 1
    win.tabs.setCurrentIndex(1)
    app.processEvents()

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "ui_smoke.png")
    win.grab().save(str(out))
    print("UI-Start-Test OK, Screenshot:", out)
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
