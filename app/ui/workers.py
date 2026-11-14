from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core import exporter, frames, grade, proxy, stabilize, thumbs, tracker, transthumbs, updater, waveform


class ExportWorker(QThread):
    progress = Signal(float)
    done = Signal(str)  # leerer String = Erfolg, sonst Fehlermeldung

    def __init__(self, cmd: list[str], total: float, parent=None, measure_path: str = ""):
        super().__init__(parent)
        self._cmd, self._total = cmd, total
        self._cancel = False
        self._measure_path = measure_path
        self.loudness: float | None = None          # nach dem Export gemessen (LUFS), falls measure_path gesetzt

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            exporter.run(self._cmd, self._total, self.progress.emit, lambda: self._cancel)
            if self._measure_path and not self._cancel:
                from ..core import loudcheck
                self.loudness = loudcheck.measure(self._measure_path)
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


class ThumbWorker(QThread):
    done = Signal(str, str, str)  # (Quelldatei, PNG-Pfad, Fehler)

    def __init__(self, src: str, duration: float, is_image: bool, parent=None):
        super().__init__(parent)
        self._src, self._dur, self._img = src, duration, is_image

    def run(self) -> None:
        try:
            self.done.emit(self._src, thumbs.make_thumb(self._src, self._dur, self._img), "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(self._src, "", str(exc))


class FrameWorker(QThread):
    """Ein Bild des Projekts (ohne Effekte) für den Masken-Rahmen."""
    done = Signal(str, str)  # (PNG-Pfad, Fehler)

    def __init__(self, project, t: float, height: int, png: str, tmp_dir: str, parent=None):
        super().__init__(parent)
        self._args = (project, t, height, png, tmp_dir)

    def run(self) -> None:
        try:
            frames.frame_at(*self._args)
            self.done.emit(self._args[3], "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit("", str(exc))


class TrackWorker(QThread):
    """Verfolgt den Maskenbereich eines Effekt-Blocks (rechnet auf einer Kopie des Projekts)."""
    progress = Signal(float)
    done = Signal(object, str)  # (TrackResult | None, Fehler)

    def __init__(self, project, idx: int, parent=None):
        super().__init__(parent)
        self._project, self._idx = project, idx
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            res = tracker.track_block(self._project, self._idx, should_cancel=lambda: self._cancel,
                                      on_progress=self.progress.emit)
            self.done.emit(res, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, str(exc))


class StabilizeWorker(QThread):
    """Analysiert alle Clips, die stabilisiert werden sollen und noch keine Analyse haben."""
    progress = Signal(float)
    done = Signal(str)  # leerer String = Erfolg, sonst Fehlermeldung

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self._project = project
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            stabilize.prepare(self._project, lambda: self._cancel, self.progress.emit)
            self.done.emit("")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(str(exc))


class TransThumbWorker(QThread):
    """Erzeugt die Vorschaubilder der Übergangsliste nacheinander."""
    done = Signal(str, str, str)  # (Übergangs-ID, PNG-Pfad, Fehler)

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self._items = items            # [(id, xfade)]

    def run(self) -> None:
        for tid, name in self._items:
            try:
                self.done.emit(tid, transthumbs.make_thumb(tid, name), "")
            except Exception as exc:  # noqa: BLE001
                self.done.emit(tid, "", str(exc))


class ProxyWorker(QThread):
    """Erzeugt nacheinander Proxys. force=False: nur für „schwere“ Videos (größer als Full HD, HEVC, hohe Datenrate)."""
    progress = Signal(int, int, str, float)     # (Nummer, Anzahl, Dateiname, Anteil)
    item = Signal(str, str)                     # (Quelldatei, Proxy-Pfad)
    done = Signal(str)                          # Zusammenfassung; Fehler stehen darin

    def __init__(self, files: list[str], force: bool, parent=None):
        super().__init__(parent)
        self._files, self._force = list(files), force
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        made, errors = 0, []
        n = len(self._files)
        for i, f in enumerate(self._files):
            if self._cancel:
                break
            try:
                if not self._force and not proxy.is_heavy(proxy.inspect(f)):
                    continue
                name = f.replace("\\", "/").rsplit("/", 1)[-1]
                out = proxy.make(f, lambda fr, i=i, name=name: self.progress.emit(i + 1, n, name, fr), lambda: self._cancel)
                made += 1
                self.item.emit(f, out)
            except Exception as exc:  # noqa: BLE001
                if not self._cancel:
                    errors.append(f"{f.replace(chr(92), '/').rsplit('/', 1)[-1]}: {str(exc)[-160:]}")
        msg = f"{made} Proxy(s) erstellt" if made else "Keine Proxys nötig"
        if self._cancel:
            msg = "Proxy-Erstellung abgebrochen"
        if errors:
            msg += "\n" + "\n".join(errors)
        self.done.emit(msg)
