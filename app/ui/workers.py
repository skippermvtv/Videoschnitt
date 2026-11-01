from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core import exporter, grade, updater, waveform


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


class GradePreviewWorker(QThread):
    done = Signal(str, str)  # (PNG-Pfad, Fehler)

    def __init__(self, path: str, t: float, grade_values: dict, parent=None):
        super().__init__(parent)
        self._path, self._t, self._g = path, t, grade_values

    def run(self) -> None:
        try:
            self.done.emit(grade.render_preview(self._path, self._t, self._g), "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit("", str(exc))


class WaveformWorker(QThread):
    done = Signal(str, str, str)  # (Audiodatei, PNG-Pfad, Fehler)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        try:
            self.done.emit(self._path, waveform.render(self._path), "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(self._path, "", str(exc))


class AsrWorker(QThread):
    done = Signal(object, str)  # (Liste von SubtitleCue | None, Fehler)

    def __init__(self, project_json: str, language: str, parent=None):
        super().__init__(parent)
        self._json, self._lang = project_json, language

    def run(self) -> None:
        try:
            from ..core import subtitles
            from ..core.project import Project
            cues = subtitles.transcribe_project(Project.from_json(self._json), self._lang)
            self.done.emit(cues, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, str(exc))


class WhisperSetupWorker(QThread):
    """Lädt whisper.cpp und das Sprachmodell herunter (nur was fehlt)."""
    progress = Signal(str, float)
    done = Signal(str)  # leerer String = Erfolg, "abgebrochen" oder Fehlertext

    def __init__(self, model: str = "base", parent=None):
        super().__init__(parent)
        self._model = model
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            from ..core import whisper_setup
            whisper_setup.setup_all(self._model, self.progress.emit, lambda: self._cancel)
            self.done.emit("")
        except Exception as exc:  # noqa: BLE001
            from ..core import whisper_setup as ws
            self.done.emit("abgebrochen" if isinstance(exc, ws.Cancelled) else str(exc) or exc.__class__.__name__)


class DiagnoseWorker(QThread):
    done = Signal(str)

    def run(self) -> None:
        try:
            from ..core import diagnostics
            self.done.emit(diagnostics.build_report())
        except Exception as exc:  # noqa: BLE001
            self.done.emit(f"Diagnose fehlgeschlagen: {exc}")
