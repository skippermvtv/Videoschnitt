"""Startpunkt von FATE VIDEOSCHNITT."""
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core import diagnostics
from app.paths import bundle_dir
from app.ui.main_window import MainWindow
from app.ui.theme import STYLE
from app.version import APP_NAME


class _ErrorBridge(QObject):
    """Bringt Fehlermeldungen aus beliebigen Threads sicher in den Hauptthread."""
    error = Signal(str)


def main() -> int:
    diagnostics.setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = bundle_dir() / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    bridge = _ErrorBridge()
    bridge.error.connect(win.show_crash)
    diagnostics.install_exception_hooks(bridge.error.emit)
    win.show()
    code = app.exec()
    diagnostics.log("%s beendet (Code %s)", APP_NAME, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
