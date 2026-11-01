"""Startpunkt von ClipForge."""
import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import STYLE
from app.version import APP_NAME


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
