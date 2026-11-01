from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core import exporter, updater


class ExportWorker(QThread):
    progress = Signal(float)
    done = Signal(str)  # leerer String = Erfolg, sonst Fehlermeldung

    def __init__(self, cmd: list[str], total: float, parent=None):
        super().__init__(parent)
        self._cmd, self._total = cmd, total
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            exporter.run(self._cmd, self._total, self.progress.emit, lambda: self._cancel)
            self.done.emit("")
        except Exception as exc:  # noqa: BLE001 - Fehler an die UI melden
            self.done.emit(str(exc))


class UpdateCheckWorker(QThread):
    result = Signal(object, str)  # (UpdateInfo | None, Fehlertext)

    def run(self) -> None:
        try:
            self.result.emit(updater.check(), "")
        except Exception as exc:  # noqa: BLE001
            self.result.emit(None, str(exc))


class UpdateDownloadWorker(QThread):
    progress = Signal(float)
    done = Signal(str, str)  # (Pfad, Fehler)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self._info = info

    def run(self) -> None:
        try:
            path = updater.download(self._info, self.progress.emit)
            self.done.emit(str(path), "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit("", str(exc))
