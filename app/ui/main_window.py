"""Hauptfenster von FATE VIDEOSCHNITT."""
from __future__ import annotations

import copy
import os
import tempfile
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QKeySequence, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QCheckBox, QDialog, QDialogButtonBox, QTextBrowser, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QSlider,
    QFrame, QLineEdit, QListView, QScrollArea, QSplitter, QStackedWidget, QStyle, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import paths
from ..core import effects as fx
from ..core import audiomix, chapters as chapterlib, collect as collectlib, freeze as freezelib, gaps as gapslib, selection as sellib, beats as beatlib, duplicate, gif as giflib, stillframe, karaoke, markers as markerlib, scenes, silence, keypreview, loudcheck, overlaykeys, subpreview, whatsnew, diagnostics, exporter, grade as gradelib, multiexport, preview as prevcache, presets, settings, speedramp as rampmod, split as splitlib, stabilize, subtitles as subs, titles as titlelib, updater, window as projwin
from ..core.history import History
from ..core.fontcheck import missing_chars
from ..core.helptext import help_html
from ..core.project import (IMAGE_MAX, OVERLAY_CORNERS, TRACK_NAMES, AudioClip, Clip, MediaInfo, OverlayClip,
                            TEXT_ANIMS, Project, SubtitleCue, TextLayer, is_image_path, probe, probe_audio)
from ..version import APP_NAME, VERSION
from .colorwidgets import ColorWheel, CurveEditor
from .maskcanvas import MaskCanvas
from .navtabs import NavTabs
from .theme import BRAND, MUTED
from .curveeditor import SpeedCurveEditor
from .beatdialog import BeatDialog
from .scenedialog import SceneDialog
from .silencedialog import SilenceDialog
from .whatsnewdialog import WhatsNewDialog
from .timeline import FX_MIME, MEDIA_MIME, TITLE_MIME, TRANS_MIME, Timeline
from .workers import TransThumbWorker, StabilizeWorker, TrackWorker, FrameWorker, ThumbWorker, ExportWorker, GradePreviewWorker, UpdateCheckWorker, UpdateDownloadWorker, WaveformWorker, AsrWorker, WhisperSetupWorker, DiagnoseWorker

VIDEO_FILTER = ("Videos und Bilder (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.mts *.m2ts "
                "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff);;Alle Dateien (*)")
LAYOUTS = [("", "Automatisch (vom Format)"), ("fit", "Einpassen (schwarze Balken)"),
           ("fill", "Füllen (zuschneiden)"), ("blur", "Unscharfer Hintergrund")]
AUDIO_FILTER = ("Audio und Videos (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mov *.mkv *.webm);;"
                "Alle Dateien (*)")
(TAB_MEDIA, TAB_FORMAT, TAB_GRADE, FX_TAB, TAB_TITLES, TAB_TRANS, TAB_TEXT, TAB_CLIP, AUDIO_TAB, OVERLAY_TAB, TAB_SPLIT,
 SUBTITLE_TAB, MOTION_TAB) = range(13)
SRT_FILTER = "Untertitel (*.srt);;Alle Dateien (*)"
ASR_LANGS = [("auto", "Automatisch erkennen"), ("de", "Deutsch"), ("en", "Englisch"), ("pl", "Polnisch"),
             ("es", "Spanisch"), ("fr", "Französisch"), ("it", "Italienisch"), ("tr", "Türkisch"), ("ru", "Russisch")]
TEXT_POS = [("top", "Oben"), ("center", "Mitte"), ("bottom", "Unten")]


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


class MediaList(QListWidget):
    """Medienraster: Einträge lassen sich auf die Timeline ziehen (legt sie an der Stelle ein)."""

    def mimeData(self, items):  # noqa: N802
        md = QMimeData()
        md.setText(MEDIA_MIME + "\n".join(str(it.data(Qt.ItemDataRole.UserRole)) for it in items))
        return md


class TagList(QListWidget):
    """Liste, deren Einträge sich auf die Timeline ziehen lassen; `tag` + Kennung der Einträge (UserRole) wird mitgegeben."""

    def __init__(self, tag: str, parent=None):
        super().__init__(parent)
        self._tag = tag

    def mimeData(self, items):  # noqa: N802
        md = QMimeData()
        md.setText(self._tag + "\n".join(str(it.data(Qt.ItemDataRole.UserRole)) for it in items[:1]))
        return md


class PreviewVideo(QVideoWidget):
    """Player-Bild: Doppelklick = Vollbild; im Vollbild startet/stoppt Klick oder Leertaste die Wiedergabe (Esc beendet)."""
    toggle_requested = Signal()

    def mouseDoubleClickEvent(self, ev):  # noqa: N802
        self.setFullScreen(not self.isFullScreen())

    def mousePressEvent(self, ev):  # noqa: N802
        if self.isFullScreen():
            self.toggle_requested.emit()
        else:
            super().mousePressEvent(ev)

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key.Key_Space:
            self.toggle_requested.emit()
        else:
            super().keyPressEvent(ev)


class SeekSlider(QSlider):
    """Suchleiste: ein Klick irgendwo auf der Leiste springt dorthin (nicht nur seitenweise)."""

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton and self.maximum() > 0:
            v = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(ev.position().x()),
                                               max(1, self.width()))
            self.setValue(v)
            self.sliderMoved.emit(v)
        super().mousePressEvent(ev)


class FxTree(QTreeWidget):
    """Effektliste: Einträge lassen sich auf die FX-Spur der Timeline ziehen."""

    def mimeData(self, items):
        md = QMimeData()
        ids = [it.data(0, Qt.ItemDataRole.UserRole) for it in items if it.data(0, Qt.ItemDataRole.UserRole)]
        if ids:
            md.setText(FX_MIME + ids[0])
        return md


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = Project()
        self.media: dict[str, MediaInfo] = {}
        self.sel = -1
        self.asel = -1          # gewählter Audioblock
        self.osel = -1          # gewähltes Bild-in-Bild
        self._loading = False
        self._waves: dict = {}
        self._wave_pending: set[str] = set()
        self._wave_workers: list = []
        self._asr_worker = None
        self._asr_then = None
        self._preview_path = ""        # Datei, die gerade als Vorschau läuft
        self._preview_start = 0.0
        self._job_t0 = 0.0
        self._sub_color = "#ffffff"
        self._sub_kar_color = "#ffd400"
        self._fonts: dict[str, str] = {}
        self.fsel = -1          # gewählter Effekt-Block auf der FX-Spur
        self._text_color = "#ffffff"
        self._cur_path = ""
        self._pending_seek: int | None = None
        self._autoplay = False
        self._limit_ms: int | None = None
        self._project_file = ""
        self._worker = None
        self._multi_jobs: list = []
        self._multi_ok: list = []
        self._multi_loud: list = []
        self._last_loudness: float | None = None
        self._multi_total = 0
        self._tmp_dirs: list[Path] = []
        self._grade_worker = None
        self._grade_dirty = False
        self._grade_sliders: dict[str, QSlider] = {}
        self._grade_labels: dict[str, QLabel] = {}
        self._grade_timer = QTimer(self)
        self._grade_timer.setSingleShot(True)
        self._grade_timer.setInterval(250)
        self._grade_timer.timeout.connect(self._update_grade_preview)
        # Live-Vorschau: nach jeder Änderung rechnet ein Hintergrundauftrag einen kurzen Ausschnitt am Abspielkopf neu
        _cfg = settings.load()
        self._live_on = bool(_cfg.get("live_preview", True))
        self._live_len_cfg = max(2.0, min(30.0, float(_cfg.get("live_len", 6.0))))
        self._live_worker = None
        self._live_pending: tuple | None = None
        self._live_path = ""            # Datei der Live-Vorschau, die gerade im Player liegt
        self._live_state = ""           # Projektstand, aus dem sie berechnet wurde
        self._live_start_t = 0.0
        self._live_len = 0.0
        self._live_next_ready: tuple | None = None      # (Start, Datei, Projektstand) des vorab gerechneten nächsten Abschnitts
        self._live_playing = False
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._live_fire)
        self._thumb_workers: list = []
        self._frame_workers: list = []
        self._mask_frame_token = 0
        self._mask_edit_idx = -1
        self._track_worker = None
        self._track_target = None
        self._stab_worker = None
        self._stab_then: list = []
        self._stab_fail_state = ""

        self._history = History(self.project.to_json())
        self._saved_state = self.project.to_json()
        self._live_last_state = self._saved_state
        self._ask_on_close = not os.environ.get("CLIPFORGE_NO_PROMPTS")
        self._hist_timer = QTimer(self)
        self._hist_timer.setInterval(250)
        self._hist_timer.timeout.connect(self._hist_tick)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(30000)
        self._autosave_timer.timeout.connect(self.autosave_now)

        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        icon = paths.bundle_dir() / "assets" / "icon.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1480, 880)
        self.setAcceptDrops(True)
        self._load_fonts()
        self._build_ui()
        self._build_actions()
        self._populate_presets()
        self._sync_controls_from_project()
        self._refresh_timeline()
        if self._ask_on_close:                 # nur im echten Programm, Tests lassen die Einstellungen in Ruhe
            self._restore_ui()
        prevcache.cleanup()
        self._hist_timer.start()
        self._autosave_timer.start()
        if self._ask_on_close:
            QTimer.singleShot(900, self._offer_restore)
            QTimer.singleShot(1500, self._check_whats_new)
        QTimer.singleShot(600, self._start_trans_thumbs)
        if updater.configured():
            QTimer.singleShot(2500, lambda: self.check_updates(silent=True))

    # ------------------------------------------------------------ Was ist neu
    def _changelog_text(self) -> str:
        for base in (paths.bundle_dir(), paths.bundle_dir().parent):
            f = base / "CHANGELOG.md"
            try:
                if f.is_file():
                    return f.read_text(encoding="utf-8")
            except OSError:
                pass
        return ""

    def _check_whats_new(self, force: bool = False) -> bool:
        """Nach einem Versionswechsel die Änderungen zeigen. Gibt zurück, ob das Fenster gezeigt wurde."""
        st = settings.load()
        existed = settings.exists()
        items = whatsnew.decide(st.get("last_version", ""), VERSION, existed, self._changelog_text())
        if st.get("last_version") != VERSION:
            settings.save({"last_version": VERSION})
        if not items or (st.get("whatsnew_off") and not force):
            return False
        dlg = WhatsNewDialog(APP_NAME, VERSION, whatsnew.to_html(items), self)
        self._whatsnew_dialog = dlg
        dlg.exec()
        if dlg.off.isChecked():
            settings.save({"whatsnew_off": True})
        return True

    # ------------------------------------------------------------ Schriften
    def _load_fonts(self) -> None:
        self._fonts.clear()
        for folder in (paths.bundle_dir() / "fonts", paths.user_fonts_dir()):
            if not folder.exists():
                continue
            for f in sorted(list(folder.glob("*.ttf")) + list(folder.glob("*.otf"))):
                fid = QFontDatabase.addApplicationFont(str(f))
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                self._fonts[f.stem] = str(f)
                if fams and not hasattr(self, "_brand_family"):
                    self._brand_family = fams[0]

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        vsplit = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(vsplit)
        top = QSplitter(Qt.Orientation.Horizontal)
        vsplit.addWidget(top)

        # Reihenfolge wie früher: Player und Timeline existieren, bevor die Reiter gebaut werden
        preview_panel = self._build_preview_panel()
        # -- unten: Timeline mit Werkzeugleiste
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(2)
        self._tl_bar = QHBoxLayout()
        self._tl_bar.setContentsMargins(4, 2, 4, 0)
        bv.addLayout(self._tl_bar)
        self.timeline = Timeline()
        self.timeline.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.timeline.clip_selected.connect(self._select_clip)
        self.timeline.audio_selected.connect(self._select_audio)
        self.timeline.overlay_selected.connect(self._select_overlay)
        self.timeline.overlay_edited.connect(self._on_overlay_edited)
        self.timeline.clip_edited.connect(self._on_clip_edited)
        self.timeline.clip_reordered.connect(self._reorder_clip)
        self.timeline.seek_requested.connect(self._seek_project)
        self.timeline.audio_edited.connect(self._on_audio_edited)
        self.timeline.fx_selected.connect(self._select_fx)
        self.timeline.fx_edited.connect(self._on_fx_edited)
        self.timeline.multi_changed.connect(self._on_multi_changed)
        self.timeline.multi_edited.connect(self._on_multi_edited)
        self.timeline.effect_dropped.connect(self._on_fx_dropped)
        self.timeline.media_dropped.connect(self._on_media_dropped)
        self.timeline.title_dropped.connect(self._on_title_dropped)
        self.timeline.transition_dropped.connect(self._on_transition_dropped)
        self.timeline.lane_mute_toggled.connect(self._on_lane_mute)
        bv.addWidget(self.timeline, 1)


        # -- oben links: Reiter (Medien, Format, Bild, Effekte …) mit Export-Knopf
        self.tabs = NavTabs()
        self.tabs.addTab(self._build_media_tab(), "Medien", "▣")
        self.tabs.addTab(self._build_format_tab(), "Format", "▭")
        self.tabs.addTab(self._build_grade_tab(), "Bild", "◐")
        self.tabs.addTab(self._build_effects_tab(), "Effekte", "✦")
        self.tabs.addTab(self._build_titles_tab(), "Titel", "Ａ")
        self.tabs.addTab(self._build_transitions_tab(), "Übergänge", "⇄")
        self.tabs.addTab(self._build_text_tab(), "Text", "T")
        self.tabs.addTab(self._build_clip_tab(), "Clip", "✂")
        self.tabs.addTab(self._build_audio_tab(), "Ton", "♪")
        self.tabs.addTab(self._build_overlay_tab(), "Bild-in-Bild", "❏")
        self.tabs.addTab(self._build_split_tab(), "Split", "▥")
        self.tabs.addTab(self._build_subtitle_tab(), "Untertitel", "≣")
        self.tabs.addTab(self._build_motion_tab(), "Bewegung", "➤")
        self.btn_export = QPushButton("EXPORT")
        self.btn_export.setObjectName("primary")
        self.btn_export.setToolTip("Video exportieren (Strg+E)")
        self.btn_export.clicked.connect(self.export_video)
        self.tabs.setCornerWidget(self.btn_export)
        top.addWidget(self.tabs)

        # -- oben rechts: Vorschau
        top.addWidget(preview_panel)
        top.setStretchFactor(0, 0)
        top.setStretchFactor(1, 1)
        top.setSizes([700, 760])
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        vsplit.setSizes([520, 340])
        self._hsplit, self._vsplit = top, vsplit

        self.statusBar().showMessage("Bereit. Ziehe Videodateien ins Fenster, um zu starten.")

    def _build_media_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        b1 = QPushButton("＋ Importieren …")
        b1.clicked.connect(self.import_dialog)
        row.addWidget(b1)
        self.media_search = QLineEdit()
        self.media_search.setPlaceholderText("Suchen …")
        self.media_search.setClearButtonEnabled(True)
        self.media_search.textChanged.connect(self._filter_media)
        row.addWidget(self.media_search, 1)
        v.addLayout(row)
        self.media_hint = QLabel("Noch keine Medien.\nZiehe Videos, Bilder oder Audiodateien ins Fenster\noder klicke auf „Importieren“.")
        self.media_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.media_hint.setStyleSheet(f"color: {MUTED};")
        v.addWidget(self.media_hint)
        self.media_list = MediaList()
        self.media_list.setObjectName("medialist")
        self.media_list.setDragEnabled(True)
        self.media_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.media_list.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.media_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.media_list.setViewMode(QListView.ViewMode.IconMode)
        self.media_list.setIconSize(QSize(160, 90))
        self.media_list.setGridSize(QSize(176, 134))
        self.media_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.media_list.setMovement(QListView.Movement.Static)
        self.media_list.setWordWrap(True)
        self.media_list.setUniformItemSizes(True)
        self.media_list.itemDoubleClicked.connect(lambda it: self._add_to_timeline(it.data(Qt.ItemDataRole.UserRole)))
        self.media_list.currentItemChanged.connect(self._on_media_selected)
        v.addWidget(self.media_list, 1)
        b2 = QPushButton("Zur Timeline hinzufügen  ▶")
        b2.setToolTip("Auch per Doppelklick auf das Vorschaubild – oder das Bild direkt auf die Timeline ziehen")
        b2.clicked.connect(self._add_selected_media)
        v.addWidget(b2)
        return w

    def _build_titles_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.addWidget(QLabel("Titel-Vorlagen – Doppelklick legt den Titel am Abspielkopf an, oder auf die Timeline ziehen."))
        self.title_list = TagList(TITLE_MIME)
        self.title_list.setDragEnabled(True)
        self.title_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.title_list.setDefaultDropAction(Qt.DropAction.CopyAction)
        for t in titlelib.templates():
            it = QListWidgetItem(f"{t['name']}\n{t.get('info', '')}")
            it.setData(Qt.ItemDataRole.UserRole, t["id"])
            self.title_list.addItem(it)
        self.title_list.itemDoubleClicked.connect(lambda it: self.add_title(it.data(Qt.ItemDataRole.UserRole)))
        v.addWidget(self.title_list, 1)
        b = QPushButton("＋ Am Abspielkopf einfügen")
        b.clicked.connect(lambda: self.add_title(None))
        v.addWidget(b)
        hint = QLabel("Danach im Reiter „Text“ den Wortlaut, die Schrift und die Zeiten ändern.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED};")
        v.addWidget(hint)
        return w

    def _build_transitions_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.addWidget(QLabel("Übergänge – Doppelklick legt ihn hinter den gewählten Clip, oder auf eine Clipgrenze ziehen."))
        self.trans_list = TagList(TRANS_MIME)
        self.trans_list.setObjectName("medialist")
        self.trans_list.setViewMode(QListView.ViewMode.IconMode)
        self.trans_list.setIconSize(QSize(120, 68))
        self.trans_list.setGridSize(QSize(136, 100))
        self.trans_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.trans_list.setMovement(QListView.Movement.Static)
        self.trans_list.setWordWrap(True)
        self.trans_list.setDragEnabled(True)
        self.trans_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.trans_list.setDefaultDropAction(Qt.DropAction.CopyAction)
        for t in presets.load("transitions"):
            it = QListWidgetItem(t["name"])
            it.setData(Qt.ItemDataRole.UserRole, t["id"])
            self.trans_list.addItem(it)
        self.trans_list.itemDoubleClicked.connect(lambda it: self.apply_transition(it.data(Qt.ItemDataRole.UserRole)))
        v.addWidget(self.trans_list, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Dauer"))
        self.trans_dur = QDoubleSpinBox()
        self.trans_dur.setRange(0.1, 5.0)
        self.trans_dur.setSingleStep(0.1)
        self.trans_dur.setSuffix(" s")
        self.trans_dur.setValue(0.8)
        row.addWidget(self.trans_dur)
        row.addStretch(1)
        v.addLayout(row)
        r2 = QHBoxLayout()
        b1 = QPushButton("Auf gewählten Clip")
        b1.setToolTip("Übergang zwischen dem gewählten und dem nächsten Clip")
        b1.clicked.connect(lambda: self.apply_transition(None))
        b2 = QPushButton("Auf alle Clips")
        b2.clicked.connect(lambda: self.apply_transition(None, all_clips=True))
        b3 = QPushButton("Entfernen")
        b3.setToolTip("Harter Schnitt nach dem gewählten Clip")
        b3.clicked.connect(lambda: self.apply_transition("", None))
        for b in (b1, b2, b3):
            r2.addWidget(b)
        v.addLayout(r2)
        return w

    def _build_split_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        hint = QLabel("Split Screen: Mehrere Videos laufen nebeneinander im Bild. Lege sie als Bild-in-Bild zur selben Zeit "
                      "auf V2 (oder markiere unten Medien und klicke „Medien als Split einfügen“), wähle ein Layout und "
                      "klicke „Anwenden“. Jedes Video füllt sein Feld aus, überstehende Ränder werden abgeschnitten. "
                      "Der Ton des Hauptvideos bleibt unverändert.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED};")
        v.addWidget(hint)
        form = QFormLayout()
        self.split_layout = QComboBox()
        glyph = {"2h": "▌▐", "2v": "▀▄", "3l": "▌▝▗", "3c": "▌▌▌", "4": "▛▜▙▟"}
        for lid, name, cells in splitlib.LAYOUTS:
            self.split_layout.addItem(f"{glyph.get(lid, '')}  {name}  ({len(cells)} Videos)", lid)
        form.addRow("Layout", self.split_layout)
        self.split_main = QComboBox()
        self.split_main.addItem("Hauptvideo nicht im Split", "")
        self.split_main.addItem("Hauptvideo im ersten Feld", "first")
        self.split_main.addItem("Hauptvideo im letzten Feld", "last")
        self.split_main.setToolTip("Dann braucht es ein Bild-in-Bild weniger: das Hauptvideo (V1) füllt das Feld selbst.")
        form.addRow("Hauptvideo", self.split_main)
        self.split_gap = QDoubleSpinBox()
        self.split_gap.setRange(0.0, 10.0)
        self.split_gap.setSingleStep(0.5)
        self.split_gap.setDecimals(1)
        self.split_gap.setSuffix(" %")
        self.split_gap.setToolTip("Breite der Trennlinie zwischen den Feldern (in % der Bildbreite). 0 = keine Linie.")
        form.addRow("Trennlinie", self.split_gap)
        self.split_line = QComboBox()
        for label, col in (("Schwarz", "#000000"), ("Weiß", "#ffffff"), ("Rot", "#e53935"), ("Türkis", "#17c3b2")):
            self.split_line.addItem(label, col)
        form.addRow("Linienfarbe", self.split_line)
        v.addLayout(form)
        b1 = QPushButton("Anwenden (gewählter Block + gleichzeitige Blöcke)")
        b1.clicked.connect(lambda *_: self.apply_split())
        b2 = QPushButton("Gewählte Medien als Split einfügen")
        b2.setToolTip("In der Medienliste Videos oder Bilder markieren (Strg+Klick), dann hier klicken.")
        b2.clicked.connect(lambda *_: self.split_from_media())
        b3 = QPushButton("Split aufheben")
        b3.clicked.connect(lambda *_: self.clear_split())
        for b in (b1, b2, b3):
            v.addWidget(b)
        self.split_info = QLabel("")
        self.split_info.setWordWrap(True)
        self.split_info.setStyleSheet(f"color: {MUTED};")
        v.addWidget(self.split_info)
        v.addStretch(1)
        return w

    def _split_layout_id(self) -> str:
        return str(self.split_layout.currentData() or "2h")

    def _split_gap(self) -> float:
        v = self.split_gap.value()
        return float(v) if isinstance(v, (int, float)) else 0.0

    def _split_line(self) -> str:
        c = self.split_line.currentData()
        return c if isinstance(c, str) else "#000000"

    def _split_main(self) -> str:
        m = self.split_main.currentData()
        return m if m in ("first", "last") else ""

    def _split_status(self, text: str) -> None:
        self.split_info.setText(text)
        self.statusBar().showMessage(text)

    def apply_split(self, layout_id: str | None = None) -> list[int]:
        """Teilt das Bild: der gewählte Bild-in-Bild-Block und die gleichzeitig laufenden bekommen je ein Feld."""
        lid = layout_id or self._split_layout_id()
        t = self.timeline.playhead if self.timeline.playhead >= 0 else 0.0
        try:
            used = splitlib.apply(self.project, lid, self.osel, t, gap=self._split_gap(), line=self._split_line(),
                                  main=self._split_main())
        except splitlib.SplitError as exc:
            self._split_status(str(exc))
            return []
        self.osel = used[0]
        self.asel = -1
        self._refresh_timeline()
        self._load_overlay_fields()
        self._split_status(f"Split „{splitlib.layout(lid)[0]}“ angewendet ({len(used)} Videos).")
        return used

    def split_from_media(self, layout_id: str | None = None) -> list[int]:
        """Fügt die in der Medienliste markierten Dateien als Bild-in-Bild an der Abspielposition ein und teilt das Bild."""
        lid = layout_id or self._split_layout_id()
        name, cells = splitlib.layout(lid)
        if self._split_main():
            cells = cells[1:]                      # das Hauptvideo füllt ein Feld selbst
        files = [str(it.data(Qt.ItemDataRole.UserRole)) for it in self.media_list.selectedItems()]
        if len(files) < len(cells):
            self._split_status(f"„{name}“ braucht {len(cells)} Videos – in der Medienliste sind {len(files)} markiert.")
            return []
        first = len(self.project.overlays)
        self.add_overlay_files(files[:len(cells)])
        new = list(range(first, len(self.project.overlays)))
        if len(new) < len(cells):
            self._split_status("Nicht alle Dateien konnten eingefügt werden.")
            return []
        used = splitlib.apply(self.project, lid, indices=new, gap=self._split_gap(), line=self._split_line(), main=self._split_main())
        self.osel = used[0]
        self._refresh_timeline()
        self._load_overlay_fields()
        self.tabs.setCurrentIndex(TAB_SPLIT)
        self._split_status(f"Split „{name}“ eingefügt ({len(used)} Videos).")
        return used

    def clear_split(self) -> None:
        n = splitlib.clear(self.project)
        self._refresh_timeline()
        self._load_overlay_fields()
        self._split_status(f"Split aufgehoben ({n} Blöcke)." if n else "Es gibt kein Split.")

    def _build_preview_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 0, 0, 0)
        v.setSpacing(4)
        self.video = PreviewVideo()
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.toggle_requested.connect(self.toggle_play)
        self.video.setMinimumSize(360, 200)
        self.video.setStyleSheet("background: black;")
        self.mask_canvas = MaskCanvas()
        self.mask_canvas.changed.connect(self._on_mask_canvas)
        self.view_stack = QStackedWidget()          # 0 = Player, 1 = Standbild mit Masken-Rahmen
        self.view_stack.addWidget(self.video)
        self.view_stack.addWidget(self.mask_canvas)
        v.addWidget(self.view_stack, 1)

        self.audio = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_position)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.playbackStateChanged.connect(self._on_play_state)

        # Suchleiste über die ganze Projektlänge (nicht über die Länge der gerade geladenen Datei)
        self.seek = SeekSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self._on_seek_moved)
        v.addWidget(self.seek)

        tr = QHBoxLayout()
        self.time_label = QLabel("0:00.0")
        self.time_label.setObjectName("timecode")
        self.time_label.setMinimumWidth(70)
        self.dur_label = QLabel("/ 0:00.0")
        self.dur_label.setStyleSheet(f"color: {MUTED};")
        tr.addWidget(self.time_label)
        tr.addWidget(self.dur_label)
        tr.addStretch(1)
        b_start = QToolButton()
        b_start.setText("⏮")
        b_start.setToolTip("Zum Anfang")
        b_start.clicked.connect(lambda: self._seek_project(0.0))
        self.btn_play = QToolButton()
        self.btn_play.setText("▶")
        self.btn_play.setToolTip("Abspielen / Pause (Leertaste)")
        self.btn_play.clicked.connect(self.toggle_play)
        b_end = QToolButton()
        b_end.setText("⏭")
        b_end.setToolTip("Zum Ende")
        b_end.clicked.connect(lambda: self._seek_project(max(0.0, self.project.duration - 0.05)))
        b_full = QToolButton()
        b_full.setText("⛶")
        b_full.setToolTip("Vollbild (auch Doppelklick auf das Bild; Esc beendet)")
        b_full.clicked.connect(self._fullscreen_preview)
        for b in (b_start, self.btn_play, b_end, b_full):
            tr.addWidget(b)
        tr.addStretch(1)
        self.live_label = QLabel("")
        self.live_label.setStyleSheet(f"color: {MUTED};")
        tr.addWidget(self.live_label)
        self.btn_live = QPushButton("● Live")
        self.btn_live.setObjectName("livebadge")
        self.btn_live.setCheckable(True)
        self.btn_live.setChecked(self._live_on)
        self.btn_live.setToolTip("Live-Vorschau: Änderungen (Effekte, Bild, Ton, Text …) sind nach kurzer Zeit direkt im Player zu sehen")
        self.btn_live.toggled.connect(self.set_live)
        tr.addWidget(self.btn_live)
        v.addLayout(tr)
        return w

    def _build_timeline_toolbar(self) -> None:
        """Werkzeugleiste über der Timeline (nach _build_actions, weil sie dessen Aktionen nutzt)."""
        lay = self._tl_bar

        def tool(text, tip, slot=None, action=None):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            if action is not None:
                b.setDefaultAction(action)
                b.setText(text)
                b.setToolTip(tip)
            elif slot is not None:
                b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        def sep():
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setStyleSheet("color: #343842;")
            lay.addWidget(f)

        tool("↶", "Rückgängig (Strg+Z)", action=self.act_undo)
        tool("↷", "Wiederholen (Strg+Y)", action=self.act_redo)
        sep()
        tool("🗑", "Auswahl löschen (Entf)", self.delete_selected)
        self.btn_dup = tool("⧉", "Auswahl duplizieren (Strg+D)", self.duplicate_selected)
        tool("✂", "Am Abspielkopf teilen", self.split_clip)
        tool("◀", "Clip nach links", lambda: self.move_clip(-1))
        tool("▶", "Clip nach rechts", lambda: self.move_clip(1))
        sep()
        tool("♪ trennen", "Ton vom Clip trennen", self.detach_selected_audio)
        tool("♫ +", "Musik / Audio hinzufügen …", self.add_audio_dialog)
        tool("❏ +", "Bild-in-Bild hinzufügen …", self.add_overlay_dialog)
        lay.addStretch(1)
        self.tl_dur = QLabel("")
        self.tl_dur.setStyleSheet(f"color: {MUTED};")
        lay.addWidget(self.tl_dur)
        tool("−", "Timeline verkleinern (auch Strg + Mausrad)", lambda: self.timeline.zoom_by(1 / 1.5))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 100)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.setToolTip("Timeline zoomen")
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider)
        lay.addWidget(self.zoom_slider)
        tool("＋", "Timeline vergrößern", lambda: self.timeline.zoom_by(1.5))
        tool("Alles", "Ganzes Projekt zeigen", self.timeline.zoom_fit)

    # -- Oberfläche merken (1.4.2)
    def _restore_ui(self) -> None:
        """Stellt Spursperren, Zoom, Fensteraufteilung und den letzten Reiter aus den Einstellungen wieder her."""
        from .timeline import LANE_LABELS, MAX_ZOOM
        ui = settings.clean_ui(settings.load(), len(LANE_LABELS), self.tabs.count(), MAX_ZOOM)
        self.timeline.set_locked(ui["ui_locked"])
        if ui["ui_zoom"] > 1.0:
            self.timeline.zoom_by(ui["ui_zoom"])
            self._sync_zoom_slider()
        if ui["ui_hsplit"]:
            self._hsplit.setSizes(ui["ui_hsplit"])
        if ui["ui_vsplit"]:
            self._vsplit.setSizes(ui["ui_vsplit"])
        self.tabs.setCurrentIndex(ui["ui_tab"])

    def _save_ui(self) -> None:
        try:
            settings.save({"ui_locked": self.timeline.locked_lanes(), "ui_zoom": float(self.timeline.zoom),
                           "ui_hsplit": [int(x) for x in self._hsplit.sizes()],
                           "ui_vsplit": [int(x) for x in self._vsplit.sizes()], "ui_tab": int(self.tabs.currentIndex())})
        except Exception:  # noqa: BLE001  – Speichern der Oberfläche darf das Beenden nie stören
            pass

    def _on_zoom_slider(self, v: int) -> None:
        from .timeline import MAX_ZOOM
        target = MAX_ZOOM ** (v / 100.0)
        cur = max(self.timeline.zoom, 1e-6)
        if abs(target / cur - 1.0) > 0.02:
            self.timeline.zoom_by(target / cur)

    def _sync_zoom_slider(self) -> None:
        import math
        from .timeline import MAX_ZOOM
        z = max(1.0, float(self.timeline.zoom))
        v = int(round(100.0 * math.log(z) / math.log(MAX_ZOOM))) if MAX_ZOOM > 1 else 0
        if v != self.zoom_slider.value():
            was = self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(v)
            self.zoom_slider.blockSignals(was)

    # -- Zeit / Länge
    def _update_duration(self) -> None:
        d = self.project.duration
        self.dur_label.setText(f"/ {fmt_time(d)}")
        self.tl_dur.setText(f"Gesamtlänge {fmt_time(d)}")
        self.seek.setRange(0, int(d * 1000))

    def _show_time(self, t: float) -> None:
        self.timeline.set_playhead(t)
        if not self.seek.isSliderDown():
            self.seek.setValue(int(t * 1000))
        self.time_label.setText(fmt_time(t))

    def _fullscreen_preview(self) -> None:
        if self.view_stack.currentIndex() == 1:             # Masken-Rahmen offen: erst schließen
            self._mask_edit_off()
        self.video.setFullScreen(True)

    # -- Titel
    def add_title(self, tid: str | None, at: float | None = None) -> None:
        """Legt eine Titel-Vorlage als Textebene an (Standard: gewählte Vorlage, am Abspielkopf)."""
        if tid is None:
            it = self.title_list.currentItem()
            tid = it.data(Qt.ItemDataRole.UserRole) if it else None
        tpl = next((t for t in titlelib.templates() if t["id"] == tid), None)
        if tpl is None:
            self.statusBar().showMessage("Zuerst eine Titel-Vorlage in der Liste wählen.")
            return
        start = max(0.0, self.timeline.playhead if at is None else at)
        layer = titlelib.make_layer(tpl, start, self._fonts, "")           # "" = Standardschrift (hat „ “ – … im Gegensatz zur Metal-Schrift)
        self.project.texts.append(layer)
        self.text_list.addItem(self._text_title(layer))
        self.text_list.setCurrentRow(len(self.project.texts) - 1)
        self.tabs.setCurrentIndex(TAB_TEXT)
        self.statusBar().showMessage(f"Titel „{tpl['name']}“ eingefügt – im Reiter „Text“ kannst du ihn ändern.")

    def _on_title_dropped(self, tid: str, t: float) -> None:
        self.add_title(tid, t)

    # -- Übergänge
    def apply_transition(self, tid: str | None, idx: int | None = None, all_clips: bool = False) -> None:
        """Setzt den Übergang nach Clip `idx` (Standard: gewählter Clip). tid "" = harter Schnitt, None = gewählte Vorlage."""
        if tid is None:
            it = self.trans_list.currentItem()
            tid = it.data(Qt.ItemDataRole.UserRole) if it else None
            if tid is None:
                self.statusBar().showMessage("Zuerst einen Übergang in der Liste wählen.")
                return
        n = len(self.project.clips)
        targets = list(range(n - 1)) if all_clips else [self.sel if idx is None else idx]
        targets = [i for i in targets if 0 <= i < n - 1]
        if not targets:
            self.statusBar().showMessage("Ein Übergang braucht einen Clip, auf den noch ein weiterer folgt.")
            return
        for i in targets:
            c = self.project.clips[i]
            c.transition = tid
            if tid:
                c.transition_dur = self.trans_dur.value()
        self.project.sync_linked()
        self._refresh_timeline(select=targets[0] if not all_clips else self.sel)
        name = next((t["name"] for t in presets.load("transitions") if t["id"] == tid), "") if tid else "harter Schnitt"
        self.statusBar().showMessage(f"Übergang „{name}“ gesetzt ({len(targets)} Clip{'s' if len(targets) != 1 else ''}).")

    def _on_transition_dropped(self, tid: str, idx: int) -> None:
        self.apply_transition(tid, idx)

    def _start_trans_thumbs(self) -> None:
        items = [(t["id"], t.get("xfade", "fade")) for t in presets.load("transitions")]
        w = TransThumbWorker(items, self)
        self._thumb_workers.append(w)
        w.done.connect(self._on_trans_thumb)
        w.finished.connect(lambda w=w: self._thumb_workers.remove(w) if w in self._thumb_workers else None)
        w.start()

    def _on_trans_thumb(self, tid: str, png: str, err: str) -> None:
        if err or not png:
            return
        for i in range(self.trans_list.count()):
            it = self.trans_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == tid:
                it.setIcon(QIcon(QPixmap(png)))
                break

    def _on_media_dropped(self, files: list, idx: int) -> None:
        for k, f in enumerate(files):
            self._add_to_timeline(f, at=idx + k)

    def _on_lane_mute(self, lane: int) -> None:
        cb = self._mix_mutes.get(lane)
        if cb is not None:
            cb.setChecked(not cb.isChecked())            # der Schalter im Reiter „Ton“ schreibt ins Projekt
        self.timeline.update()

    def _on_play_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("❚❚" if playing else "▶")

    def _on_seek_moved(self, v: int) -> None:
        self._seek_project(v / 1000.0)

    def _build_format_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.cmb_format = QComboBox()
        self.cmb_format.currentIndexChanged.connect(self._on_format_changed)
        self.cmb_layout = QComboBox()
        for key, label in LAYOUTS:
            self.cmb_layout.addItem(label, key)
        self.cmb_layout.currentIndexChanged.connect(self._on_layout_changed)
        self.cmb_export = QComboBox()
        self.cmb_export.currentIndexChanged.connect(self._on_export_changed)
        self.sp_fade_in = QDoubleSpinBox()
        self.sp_fade_out = QDoubleSpinBox()
        for sp in (self.sp_fade_in, self.sp_fade_out):
            sp.setRange(0.0, 10.0)
            sp.setSingleStep(0.1)
            sp.setSuffix(" s")
            sp.valueChanged.connect(self._on_fades_changed)
        self.format_info = QLabel("")
        self.format_info.setWordWrap(True)
        self.format_info.setStyleSheet(f"color: {MUTED};")
        form.addRow("Zielformat", self.cmb_format)
        form.addRow("Anpassung", self.cmb_layout)
        form.addRow("Export-Qualität", self.cmb_export)
        form.addRow("Einblenden", self.sp_fade_in)
        form.addRow("Ausblenden", self.sp_fade_out)
        form.addRow(self.format_info)

        self.wm_name = QLabel("kein Logo")
        self.wm_name.setStyleSheet(f"color: {MUTED};")
        self.wm_pick = QPushButton("Logo wählen …")
        self.wm_clear = QPushButton("Entfernen")
        self.wm_corner = QComboBox()
        for key, label in exporter.WM_CORNERS.items():
            self.wm_corner.addItem(label, key)
        self.wm_corner.setCurrentIndex(self.wm_corner.findData("br"))
        self.wm_size = QDoubleSpinBox()
        self.wm_size.setRange(2.0, 80.0)
        self.wm_size.setSingleStep(1.0)
        self.wm_size.setSuffix(" % der Breite")
        self.wm_size.setValue(14.0)
        self.wm_opacity = QDoubleSpinBox()
        self.wm_opacity.setRange(0.0, 100.0)
        self.wm_opacity.setSingleStep(5.0)
        self.wm_opacity.setSuffix(" %")
        self.wm_opacity.setValue(80.0)
        self.wm_pick.clicked.connect(lambda *_: self.pick_watermark())
        self.wm_clear.clicked.connect(lambda *_: self.clear_watermark())
        self.wm_corner.currentIndexChanged.connect(self._on_wm_changed)
        self.wm_size.valueChanged.connect(self._on_wm_changed)
        self.wm_opacity.valueChanged.connect(self._on_wm_changed)
        wm_row = QHBoxLayout()
        wm_row.addWidget(self.wm_pick)
        wm_row.addWidget(self.wm_clear)
        head_wm = QLabel("Wasserzeichen / Logo")
        head_wm.setStyleSheet("font-weight: bold;")
        form.addRow(head_wm)
        form.addRow(wm_row)
        form.addRow(self.wm_name)
        form.addRow("Ecke", self.wm_corner)
        form.addRow("Größe", self.wm_size)
        form.addRow("Deckkraft", self.wm_opacity)

        head_sub = QLabel("Untertitel beim Export")
        head_sub.setStyleSheet("font-weight: bold;")
        self.chk_sub_burn = QCheckBox("Untertitel ins Bild einbrennen")
        self.chk_sub_burn.setChecked(True)
        self.chk_sub_burn.setToolTip("Aus: Das Video bleibt ohne Text im Bild – sinnvoll, wenn die Untertitel nur als Datei zu YouTube sollen.")
        self.chk_sub_srt = QCheckBox("Untertitel zusätzlich als .srt-Datei neben das Video speichern")
        self.chk_sub_srt.setToolTip("Die Datei heißt wie das Video (Mein Film.srt). YouTube: Video → Untertitel → Datei hochladen. "
                                    "Gibt es noch keine Untertitel, fragt das Programm beim Export, ob es sie automatisch erzeugen soll.")
        self.chk_sub_burn.toggled.connect(self._on_sub_export_changed)
        self.chk_sub_srt.toggled.connect(self._on_sub_export_changed)
        form.addRow(head_sub)
        form.addRow(self.chk_sub_burn)
        form.addRow(self.chk_sub_srt)

        cfg = settings.load()
        self.cmb_prev_len = QComboBox()
        for sec, label in prevcache.PREVIEW_LENGTHS:
            self.cmb_prev_len.addItem(label, sec)
        self.cmb_prev_len.setCurrentIndex(max(0, self.cmb_prev_len.findData(float(cfg["preview_len"]))))
        self.cmb_prev_q = QComboBox()
        for h, label in prevcache.PREVIEW_QUALITIES:
            self.cmb_prev_q.addItem(label, h)
        self.cmb_prev_q.setCurrentIndex(max(0, self.cmb_prev_q.findData(int(cfg["preview_height"]))))
        self.chk_hw = QCheckBox("Grafikkarte beim Export nutzen (schneller, wenn vorhanden)")
        self.chk_hw.setChecked(bool(cfg["hw_encode"]))
        for wdg in (self.cmb_prev_len, self.cmb_prev_q):
            wdg.currentIndexChanged.connect(self._on_perf_changed)
        self.chk_hw.toggled.connect(self._on_perf_changed)
        form.addRow(QLabel("Vorschau und Leistung"))
        form.addRow("Vorschau-Länge", self.cmb_prev_len)
        form.addRow("Vorschau-Qualität", self.cmb_prev_q)
        form.addRow(self.chk_hw)
        hint = QLabel("„Vorschau ab Abspielkopf“ (Strg+P) rechnet Effekte, Text, Ton und Übergänge in kleiner Auflösung "
                      "und spielt das Ergebnis ab. Unveränderte Vorschauen starten sofort aus dem Zwischenspeicher.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED};")
        form.addRow(hint)
        return w

    def _build_effects_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Look:"))
        self.cmb_look = QComboBox()
        self.cmb_look.activated.connect(self._on_look_chosen)
        row.addWidget(self.cmb_look, 1)
        v.addLayout(row)

        self.fx_tree = FxTree()
        self.fx_tree.setHeaderHidden(True)
        self.fx_tree.setDragEnabled(True)
        self.fx_tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.fx_tree.setDefaultDropAction(Qt.DropAction.CopyAction)   # Ziehen kopiert: der Effekt bleibt in der Liste
        for cat, items in fx.categories().items():
            top = QTreeWidgetItem([cat])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.fx_tree.addTopLevelItem(top)
            for e in items:
                it = QTreeWidgetItem([e.name])
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                it.setData(0, Qt.ItemDataRole.UserRole, e.id)
                top.addChild(it)
            top.setExpanded(True)
        self.fx_tree.itemDoubleClicked.connect(lambda *_: self.add_effect_block())
        v.addWidget(self.fx_tree, 1)

        br = QHBoxLayout()
        self.btn_fx_add = QPushButton("＋ Auf Effekt-Spur (am Abspielkopf)")
        self.btn_fx_add.clicked.connect(lambda: self.add_effect_block())
        self.btn_fx_del = QPushButton("Block entfernen")
        self.btn_fx_del.clicked.connect(self.remove_effect_block)
        br.addWidget(self.btn_fx_add, 1)
        br.addWidget(self.btn_fx_del)
        v.addLayout(br)

        self.fx_box = QGroupBox("Gewählter Effekt-Block")
        fl = QFormLayout(self.fx_box)
        self.fx_int = QSlider(Qt.Orientation.Horizontal)
        self.fx_int.setRange(0, 100)
        self.fx_int_label = QLabel("0")
        ir = QHBoxLayout()
        ir.addWidget(self.fx_int, 1)
        ir.addWidget(self.fx_int_label)
        fl.addRow("Stärke", ir)
        self.fx_start = QDoubleSpinBox()
        self.fx_end = QDoubleSpinBox()
        for sp in (self.fx_start, self.fx_end):
            sp.setRange(0.0, 36000.0)
            sp.setSingleStep(0.5)
            sp.setSuffix(" s")
        fl.addRow("Von", self.fx_start)
        fl.addRow("… bis (0 = Ende)", self.fx_end)
        self.fx_int.valueChanged.connect(self._on_fx_param)
        self.fx_start.valueChanged.connect(self._on_fx_param)
        self.fx_end.valueChanged.connect(self._on_fx_param)
        self.fx_box.setEnabled(False)
        v.addWidget(self.fx_box)

        # Bereich (nur bei Masken-Effekten): Form, Mitte, Größe, weiche Kante
        self.fx_mask_box = QGroupBox("Bereich (Maske)")
        ml = QFormLayout(self.fx_mask_box)
        self.mask_shape = QComboBox()
        self.mask_shape.addItem("Ellipse", "ellipse")
        self.mask_shape.addItem("Rechteck", "rect")
        ml.addRow("Form", self.mask_shape)
        self.mask_x, self.mask_y, self.mask_w, self.mask_h = (QDoubleSpinBox() for _ in range(4))
        for sp, lo, hi, label in ((self.mask_x, 0, 100, "Mitte links–rechts"), (self.mask_y, 0, 100, "Mitte oben–unten"),
                                  (self.mask_w, 1, 200, "Breite"), (self.mask_h, 1, 200, "Höhe")):
            sp.setRange(lo, hi)
            sp.setSingleStep(1.0)
            sp.setSuffix(" %")
            ml.addRow(label, sp)
        self.mask_feather = QSlider(Qt.Orientation.Horizontal)
        self.mask_feather.setRange(0, 100)
        ml.addRow("Weiche Kante", self.mask_feather)
        self.mask_invert = QCheckBox("Außen statt innen wirken")
        ml.addRow(self.mask_invert)
        self.btn_mask_edit = QPushButton("Bereich im Vorschaubild festlegen")
        self.btn_mask_edit.setCheckable(True)
        self.btn_mask_edit.setToolTip("Zeigt ein Bild an der Stelle des Abspielkopfs: Rahmen verschieben und an den Rändern ziehen")
        self.btn_mask_edit.toggled.connect(self._mask_edit_toggled)
        ml.addRow(self.btn_mask_edit)
        tr_row = QHBoxLayout()
        self.btn_track = QPushButton("Objekt verfolgen")
        self.btn_track.setToolTip("Der Bereich wandert über die Länge des Blocks (höchstens 30 s) mit dem Objekt mit, das im Rahmen liegt")
        self.btn_track.clicked.connect(self._track_start)
        self.btn_track_clear = QPushButton("Pfad löschen")
        self.btn_track_clear.clicked.connect(self._track_clear)
        tr_row.addWidget(self.btn_track, 1)
        tr_row.addWidget(self.btn_track_clear)
        ml.addRow(tr_row)
        self.mask_info = QLabel("")
        self.mask_info.setWordWrap(True)
        self.mask_info.setStyleSheet(f"color: {MUTED};")
        ml.addRow(self.mask_info)
        for wdg in (self.mask_x, self.mask_y, self.mask_w, self.mask_h):
            wdg.valueChanged.connect(self._on_mask_param)
        self.mask_shape.currentIndexChanged.connect(self._on_mask_param)
        self.mask_feather.valueChanged.connect(self._on_mask_param)
        self.mask_invert.toggled.connect(self._on_mask_param)
        self.fx_mask_box.setVisible(False)
        v.addWidget(self.fx_mask_box)
        hint = QLabel("Effekt aus der Liste auf die Spur „FX Effekte“ in der Timeline ziehen (oder doppelklicken). "
                      "Block verschieben = anderer Zeitpunkt, Rand ziehen = Länge ändern. Beliebig viele Blöcke, auch vom selben Effekt.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED};")
        v.addWidget(hint)
        return w

    def _build_text_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.text_list = QListWidget()
        self.text_list.setMaximumHeight(110)
        self.text_list.currentRowChanged.connect(self._on_text_selected)
        v.addWidget(self.text_list)
        r = QHBoxLayout()
        ba = QPushButton("+ Text")
        ba.clicked.connect(self.add_text)
        bd = QPushButton("Entfernen")
        bd.clicked.connect(self.remove_text)
        r.addWidget(ba)
        r.addWidget(bd)
        v.addLayout(r)

        self.text_box = QGroupBox("Text-Einstellungen")
        form = QFormLayout(self.text_box)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setMaximumHeight(80)
        self.text_edit.textChanged.connect(self._on_text_field)
        self.text_pos = QComboBox()
        for key, label in TEXT_POS:
            self.text_pos.addItem(label, key)
        self.text_pos.currentIndexChanged.connect(self._on_text_field)
        self.text_size = QDoubleSpinBox()
        self.text_size.setRange(1.0, 30.0)
        self.text_size.setSuffix(" % der Höhe")
        self.text_size.valueChanged.connect(self._on_text_field)
        self.text_start = QDoubleSpinBox()
        self.text_end = QDoubleSpinBox()
        for sp in (self.text_start, self.text_end):
            sp.setRange(0.0, 36000.0)
            sp.setSingleStep(0.5)
            sp.setSuffix(" s")
            sp.valueChanged.connect(self._on_text_field)
        self.text_font = QComboBox()
        self.text_font.currentIndexChanged.connect(self._on_text_field)
        self.btn_font_add = QPushButton("Schrift hinzufügen …")
        self.btn_font_add.clicked.connect(self.add_font)
        self.btn_color = QPushButton("Farbe wählen")
        self.btn_color.clicked.connect(self.pick_color)
        form.addRow("Text", self.text_edit)
        form.addRow("Position", self.text_pos)
        form.addRow("Größe", self.text_size)
        form.addRow("Von", self.text_start)
        form.addRow("Bis", self.text_end)
        form.addRow("Schrift", self.text_font)
        form.addRow("", self.btn_font_add)
        form.addRow("Farbe", self.btn_color)
        self.text_anim = QComboBox()
        for key, label in TEXT_ANIMS:
            self.text_anim.addItem(label, key)
        self.text_anim.currentIndexChanged.connect(self._on_text_field)
        self.text_anim_dur = QDoubleSpinBox()
        self.text_anim_dur.setRange(0.1, 3.0)
        self.text_anim_dur.setSingleStep(0.1)
        self.text_anim_dur.setSuffix(" s")
        self.text_anim_dur.setValue(0.4)
        self.text_anim_dur.valueChanged.connect(self._on_text_field)
        self.text_boxbg = QCheckBox("Dunkler Kasten hinter dem Text")
        self.text_boxbg.toggled.connect(self._on_text_field)
        form.addRow("Animation", self.text_anim)
        form.addRow("Tempo / Dauer", self.text_anim_dur)
        form.addRow(self.text_boxbg)
        self.text_box.setEnabled(False)
        v.addWidget(self.text_box)
        v.addStretch(1)
        self._refresh_font_combo()
        return w

    def _build_grade_tab(self) -> QWidget:
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        ov.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)

        self.grade_hint = QLabel("Wähle unten in der Timeline einen Clip aus, um sein Bild zu korrigieren "
                                 "(Licht, Kontrast, Farben). Jeder Clip hat seine eigene Korrektur.")
        self.grade_hint.setWordWrap(True)
        self.grade_hint.setStyleSheet(f"color: {MUTED};")
        v.addWidget(self.grade_hint)

        self.grade_body = QWidget()
        gv = QVBoxLayout(self.grade_body)
        gv.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.grade_body)

        row = QHBoxLayout()
        row.addWidget(QLabel("Voreinstellung:"))
        self.cmb_grade = QComboBox()
        self.cmb_grade.activated.connect(self._on_grade_preset)
        row.addWidget(self.cmb_grade, 1)
        gv.addLayout(row)

        self.grade_preview = QLabel("")
        self.grade_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grade_preview.setMinimumHeight(120)
        self.grade_preview.setStyleSheet("background: #0b0c0f; border: 1px solid #2c313d; border-radius: 6px;")
        gv.addWidget(self.grade_preview)
        cap = QLabel("Oben: Original · Unten: mit Korrektur (Standbild an der Abspielposition)")
        cap.setStyleSheet(f"color: {MUTED};")
        cap.setWordWrap(True)
        gv.addWidget(cap)
        bref = QPushButton("Standbild aktualisieren")
        bref.clicked.connect(self._update_grade_preview)
        gv.addWidget(bref)

        for group in ("Licht", "Farbe", "Detail"):
            box = QGroupBox(group)
            form = QFormLayout(box)
            for prm in (p for p in gradelib.PARAMS if p.group == group):
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(prm.min, prm.max)
                sl.setValue(prm.default)
                lab = QLabel("0")
                lab.setFixedWidth(36)
                lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                sl.valueChanged.connect(lambda val, k=prm.key: self._on_grade_slider(k, val))
                hl = QHBoxLayout()
                hl.addWidget(sl, 1)
                hl.addWidget(lab)
                form.addRow(prm.name, hl)
                self._grade_sliders[prm.key] = sl
                self._grade_labels[prm.key] = lab
            gv.addWidget(box)

        # Farbräder (Schatten / Mitten / Lichter)
        wbox = QGroupBox("Farbräder (ziehen = Farbstich, Doppelklick = zurücksetzen)")
        wrow = QHBoxLayout(wbox)
        self.wheels: dict[str, ColorWheel] = {}
        for zone, title in (("lift", "Schatten"), ("mid", "Mitten"), ("gain", "Lichter")):
            col = QVBoxLayout()
            lab = QLabel(title)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wheel = ColorWheel()
            wheel.changed.connect(lambda r, g, b, z=zone: self._on_wheel(z, r, g, b))
            col.addWidget(lab)
            col.addWidget(wheel, 1)
            wrow.addLayout(col, 1)
            self.wheels[zone] = wheel
        gv.addWidget(wbox)

        # Kurven
        cbox = QGroupBox("Kurven (Klick = Punkt, Rechtsklick = löschen)")
        cv = QVBoxLayout(cbox)
        self.cmb_curve = QComboBox()
        for key, name in (("m", "Helligkeit (alle Farben)"), ("r", "Rot"), ("g", "Grün"), ("b", "Blau")):
            self.cmb_curve.addItem(name, key)
        cv.addWidget(self.cmb_curve)
        self.curve_editor = CurveEditor()
        cv.addWidget(self.curve_editor)
        bcr = QPushButton("Diese Kurve zurücksetzen")
        cv.addWidget(bcr)
        gv.addWidget(cbox)

        # LUT
        lbox = QGroupBox("LUT (Look-Tabelle, .cube)")
        lf = QVBoxLayout(lbox)
        self.lut_name = QLabel("Keine LUT geladen")
        self.lut_name.setWordWrap(True)
        self.lut_name.setStyleSheet(f"color: {MUTED};")
        lf.addWidget(self.lut_name)
        lrow = QHBoxLayout()
        self.btn_lut_load = QPushButton("LUT laden …")
        self.btn_lut_clear = QPushButton("Entfernen")
        lrow.addWidget(self.btn_lut_load, 1)
        lrow.addWidget(self.btn_lut_clear)
        lf.addLayout(lrow)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Stärke"))
        self.lut_mix = QSlider(Qt.Orientation.Horizontal)
        self.lut_mix.setRange(1, 100)
        self.lut_mix.blockSignals(True)
        self.lut_mix.setValue(100)
        self.lut_mix.blockSignals(False)
        self.lut_mix_label = QLabel("100")
        self.lut_mix_label.setFixedWidth(36)
        self.lut_mix_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mrow.addWidget(self.lut_mix, 1)
        mrow.addWidget(self.lut_mix_label)
        lf.addLayout(mrow)
        gv.addWidget(lbox)

        # Signale erst verbinden, wenn alle Felder existieren
        self.cmb_curve.currentIndexChanged.connect(self._on_curve_channel)
        self.curve_editor.changed.connect(self._on_curves_changed)
        bcr.clicked.connect(self.reset_curve)
        self.btn_lut_load.clicked.connect(self.load_lut_dialog)
        self.btn_lut_clear.clicked.connect(self.clear_lut)
        self.lut_mix.valueChanged.connect(self._on_lut_mix)

        self.grade_auto = QCheckBox("Automatisch Helligkeit und Kontrast ausgleichen")
        self.grade_auto.toggled.connect(lambda on: self._on_grade_slider("auto", 1 if on else 0))
        gv.addWidget(self.grade_auto)

        br = QHBoxLayout()
        b1 = QPushButton("Zurücksetzen")
        b1.clicked.connect(self.reset_grade)
        b2 = QPushButton("Auf alle Clips anwenden")
        b2.clicked.connect(self.apply_grade_to_all)
        br.addWidget(b1)
        br.addWidget(b2)
        gv.addLayout(br)
        v.addStretch(1)
        self.grade_body.setEnabled(False)
        return outer

    def _selected_clip(self):
        return self.project.clips[self.sel] if 0 <= self.sel < len(self.project.clips) else None

    def _load_grade_fields(self) -> None:
        c = self._selected_clip()
        self.grade_body.setEnabled(c is not None)
        self.grade_hint.setVisible(c is None)
        g = c.grade if c else {}
        self._loading = True
        for key, sl in self._grade_sliders.items():
            sl.setValue(int(g.get(key, 0)))
            self._grade_labels[key].setText(f"{sl.value():+d}" if sl.minimum() < 0 else str(sl.value()))
        self.grade_auto.setChecked(bool(g.get("auto", 0)))
        for zone, wheel in self.wheels.items():
            wheel.set_rgb(int(g.get(f"{zone}_r", 0)), int(g.get(f"{zone}_g", 0)), int(g.get(f"{zone}_b", 0)))
        self.curve_editor.set_curves(g.get("curves"))
        self._show_lut(g)
        self._loading = False
        if c:
            self._grade_timer.start()
        else:
            self.grade_preview.clear()

    def _on_grade_slider(self, key: str, val: int) -> None:
        sl = self._grade_sliders.get(key)
        if sl is not None:
            self._grade_labels[key].setText(f"{val:+d}" if sl.minimum() < 0 else str(val))
        c = self._selected_clip()
        if self._loading or c is None:
            return
        if val == 0:
            c.grade.pop(key, None)
        else:
            c.grade[key] = float(val)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self._grade_timer.start()

    def _grade_changed(self) -> None:
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self._grade_timer.start()

    def _on_wheel(self, zone: str, r: int, g: int, b: int) -> None:
        c = self._selected_clip()
        if self._loading or c is None:
            return
        for ch, val in zip("rgb", (r, g, b)):
            if val:
                c.grade[f"{zone}_{ch}"] = float(val)
            else:
                c.grade.pop(f"{zone}_{ch}", None)
        self._grade_changed()

    def _on_curve_channel(self, _idx: int = 0) -> None:
        self.curve_editor.set_channel(self.cmb_curve.currentData() or "m")

    def _on_curves_changed(self) -> None:
        c = self._selected_clip()
        if self._loading or c is None:
            return
        curves = self.curve_editor.curves()
        if curves:
            c.grade["curves"] = curves
        else:
            c.grade.pop("curves", None)
        self._grade_changed()

    def reset_curve(self) -> None:
        self.curve_editor.reset_channel()          # löst changed aus → Clip wird aktualisiert

    def _show_lut(self, g: dict) -> None:
        lut = g.get("lut") or ""
        if lut:
            gone = "" if os.path.exists(lut) else "  – DATEI FEHLT"
            self.lut_name.setText(Path(lut).name + gone)
        else:
            self.lut_name.setText("Keine LUT geladen")
        self.btn_lut_clear.setEnabled(bool(lut))
        self.lut_mix.setEnabled(bool(lut))
        mix = int(g.get("lut_mix", 100)) if lut else 100
        self.lut_mix.blockSignals(True)
        self.lut_mix.setValue(mix)
        self.lut_mix.blockSignals(False)
        self.lut_mix_label.setText(str(mix))

    def load_lut_dialog(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "LUT laden", "", "LUT-Dateien (*.cube *.3dl *.dat *.m3d);;Alle Dateien (*)")
        if f:
            self.set_lut(f)

    def set_lut(self, path: str) -> bool:
        c = self._selected_clip()
        if c is None:
            return False
        try:
            dest = gradelib.import_lut(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "LUT", f"Diese LUT kann nicht verwendet werden:\n{exc}")
            return False
        c.grade["lut"] = dest
        self._loading = True
        self._show_lut(c.grade)
        self._loading = False
        self._grade_changed()
        self.statusBar().showMessage(f"LUT „{Path(dest).name}“ auf den Clip angewendet – mit „Stärke“ abschwächen.")
        return True

    def clear_lut(self) -> None:
        c = self._selected_clip()
        if c is None:
            return
        c.grade.pop("lut", None)
        c.grade.pop("lut_mix", None)
        self._loading = True
        self._show_lut(c.grade)
        self._loading = False
        self._grade_changed()

    def _on_lut_mix(self, val: int) -> None:
        self.lut_mix_label.setText(str(val))
        c = self._selected_clip()
        if self._loading or c is None or not c.grade.get("lut"):
            return
        if val >= 100:
            c.grade.pop("lut_mix", None)
        else:
            c.grade["lut_mix"] = float(val)
        self._grade_changed()

    def _on_grade_preset(self, _idx: int) -> None:
        c = self._selected_clip()
        preset = next((p for p in presets.load("grades") if p["id"] == (self.cmb_grade.currentData() or "")), None)
        if c is None or preset is None:
            return
        c.grade = gradelib.clean(preset.get("values", {}))
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self._load_grade_fields()
        self.statusBar().showMessage(f"Voreinstellung „{preset['name']}“ auf den Clip angewendet – mit den Reglern nachjustieren.")

    def reset_grade(self) -> None:
        c = self._selected_clip()
        if c is not None:
            c.grade = {}
            self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
            self._load_grade_fields()

    def apply_grade_to_all(self) -> None:
        c = self._selected_clip()
        if c is None:
            return
        for other in self.project.clips:
            other.grade = copy.deepcopy(c.grade)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self.statusBar().showMessage(f"Bildkorrektur auf alle {len(self.project.clips)} Clips angewendet.")

    def _update_grade_preview(self) -> None:
        c = self._selected_clip()
        if c is None:
            return
        if self._grade_worker is not None:
            self._grade_dirty = True
            return
        t = c.in_pt
        if self._cur_path == c.path:
            t = self.player.position() / 1000.0
        t = min(max(t, c.in_pt), max(c.in_pt, c.out_pt - 0.05))
        w = GradePreviewWorker(c.path, t, copy.deepcopy(c.grade), self)
        w.done.connect(self._on_grade_preview_done)
        self._grade_worker = w
        w.start()

    def _on_grade_preview_done(self, png: str, err: str) -> None:
        self._grade_worker = None
        if err:
            self.grade_preview.setText("Vorschau nicht möglich:\n" + err[:200])
        else:
            pix = QPixmap(png)
            if not pix.isNull():
                self.grade_preview.setPixmap(pix.scaledToWidth(max(220, self.grade_preview.width() - 8),
                                                              Qt.TransformationMode.SmoothTransformation))
        if self._grade_dirty:
            self._grade_dirty = False
            self._update_grade_preview()

    def _build_clip_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.clip_name = QLabel("Kein Clip ausgewählt")
        self.clip_name.setWordWrap(True)
        self.clip_in = QDoubleSpinBox()
        self.clip_out = QDoubleSpinBox()
        for sp in (self.clip_in, self.clip_out):
            sp.setDecimals(2)
            sp.setRange(0.0, 36000.0)
            sp.setSingleStep(0.1)
            sp.setSuffix(" s")
            sp.valueChanged.connect(self._on_clip_field)
        self.clip_speed = QDoubleSpinBox()
        self.clip_speed.setRange(0.1, 20.0)
        self.clip_speed.setSingleStep(0.25)
        self.clip_speed.setPrefix("× ")
        self.clip_speed.setValue(1.0)
        self.clip_speed.valueChanged.connect(self._on_clip_field)
        self.clip_vol = QSlider(Qt.Orientation.Horizontal)
        self.clip_vol.setRange(0, 200)
        self.clip_vol.setValue(100)
        self.clip_vol.valueChanged.connect(self._on_clip_field)
        self.clip_vol_label = QLabel("100 %")
        vr = QHBoxLayout()
        vr.addWidget(self.clip_vol, 1)
        vr.addWidget(self.clip_vol_label)
        self.clip_dn, self.clip_dn_label, dnr = self._fix_slider(self._on_clip_field)
        self.clip_vc, self.clip_vc_label, vcr = self._fix_slider(self._on_clip_field)
        self.clip_mute = QCheckBox("Ton stummschalten")
        self.clip_mute.toggled.connect(self._on_clip_field)
        self.clip_rev = QCheckBox("Rückwärts abspielen (nur kurze Clips)")
        self.clip_rev.toggled.connect(self._on_clip_field)
        form.addRow(self.clip_name)
        form.addRow("Start im Clip", self.clip_in)
        form.addRow("Ende im Clip", self.clip_out)
        form.addRow("Geschwindigkeit", self.clip_speed)
        form.addRow("Lautstärke", vr)
        form.addRow("Rauschen entfernen", dnr)
        form.addRow("Sprache klarer", vcr)
        form.addRow(self.clip_mute)
        self.clip_audio_note = QLabel("Der Ton dieses Clips liegt als eigener Block auf A1 (Registerkarte „Ton“).")
        self.clip_audio_note.setWordWrap(True)
        self.clip_audio_note.setStyleSheet(f"color: {MUTED};")
        self.clip_audio_note.setVisible(False)
        form.addRow(self.clip_audio_note)
        form.addRow(self.clip_rev)
        self.clip_stab = QSlider(Qt.Orientation.Horizontal)
        self.clip_stab.setRange(0, 100)
        self.clip_stab.setToolTip("Verwackelte Aufnahmen beruhigen. Beim ersten Mal wird der Clip analysiert (dauert etwas), "
                                  "danach ist es gespeichert. Hohe Werte beruhigen stärker und schneiden etwas mehr vom Bildrand ab.")
        self.clip_stab.valueChanged.connect(self._on_clip_field)
        self.clip_stab_label = QLabel("aus")
        sr = QHBoxLayout()
        sr.addWidget(self.clip_stab, 1)
        sr.addWidget(self.clip_stab_label)
        form.addRow("Stabilisieren", sr)
        hint = QLabel("Zeitlupe: Geschwindigkeit unter 1, Zeitraffer: über 1.")
        hint.setStyleSheet(f"color: {MUTED};")
        form.addRow(hint)
        # --- Geschwindigkeitskurve (1.4.2)
        form.addRow(QLabel("Geschwindigkeitskurve"))
        self.ramp_preset = QComboBox()
        self.ramp_preset.addItem("– Vorlage wählen –", "")
        for rid, rname, rpts in rampmod.PRESETS:
            self.ramp_preset.addItem(rname, rid)
        self._fill_ramp_presets()
        self.ramp_preset.currentIndexChanged.connect(self._on_ramp_preset)
        self.ramp_save = QPushButton("Kurve speichern …")
        self.ramp_save.setToolTip("Speichert die Kurve unter einem Namen in der Vorlagenliste („Meine Kurven“).")
        self.ramp_save.clicked.connect(lambda *_: self.save_my_ramp())
        self.ramp_del = QPushButton("Gespeicherte löschen")
        self.ramp_del.setEnabled(False)
        self.ramp_del.clicked.connect(lambda *_: self.delete_my_ramp())
        self.ramp_text = QLineEdit()
        self.ramp_text.setPlaceholderText("Position in %:Tempo, z. B. 0:1, 50:0.25, 100:1")
        self.ramp_text.setToolTip("Punkte der Kurve als „Position im Clip in %:Tempo“, durch Komma getrennt. "
                                  "Dazwischen wird weich übergeblendet. Tempo 0.25 = Zeitlupe, 2 = doppelt so schnell.")
        self.ramp_text.textChanged.connect(self._on_ramp_text)
        self.ramp_info = QLabel("")
        self.ramp_info.setWordWrap(True)
        self.ramp_info.setStyleSheet(f"color: {MUTED};")
        self.btn_ramp = QPushButton("Kurve anwenden (teilt den Clip in Abschnitte)")
        self.btn_ramp.clicked.connect(lambda *_: self.apply_speed_ramp())
        self.btn_ramp_off = QPushButton("Kurve entfernen (Clip wieder in einem Stück)")
        self.btn_ramp_off.setEnabled(False)
        self.btn_ramp_off.clicked.connect(lambda *_: self.remove_speed_ramp())
        self.ramp_group_note = QLabel("")
        self.ramp_group_note.setWordWrap(True)
        self.ramp_group_note.setStyleSheet(f"color: {MUTED};")
        self._ramp_loaded_id = ""
        self.ramp_curve = SpeedCurveEditor()
        self.ramp_curve.pointsChanged.connect(self._on_ramp_curve)
        form.addRow("Vorlage", self.ramp_preset)
        rrow = QHBoxLayout()
        rrow.addWidget(self.ramp_save)
        rrow.addWidget(self.ramp_del)
        form.addRow(rrow)
        form.addRow(self.ramp_curve)
        form.addRow("Punkte", self.ramp_text)
        form.addRow(self.ramp_info)
        form.addRow(self.ramp_group_note)
        form.addRow(self.btn_ramp)
        form.addRow(self.btn_ramp_off)
        # --- Chroma-Key auf dem Hauptvideo (1.4.4)
        form.addRow(QLabel("Chroma-Key (Greenscreen im Hauptvideo)"))
        self.ck_on = QCheckBox("Hintergrundfarbe entfernen")
        form.addRow(self.ck_on)
        ckrow = QHBoxLayout()
        self.ck_swatch = QLabel("")
        self.ck_swatch.setFixedSize(28, 18)
        self.ck_green = QPushButton("Grün")
        self.ck_blue = QPushButton("Blau")
        self.ck_eye = QPushButton("Pipette …")
        self.ck_pick = QPushButton("Andere Farbe …")
        for ck_w in (self.ck_swatch, self.ck_green, self.ck_blue, self.ck_eye):     # nicht „w“: das ist die Seite des Reiters
            ckrow.addWidget(ck_w)
        ckrow.addWidget(self.ck_pick, 1)
        form.addRow(ckrow)
        self.ck_sim = QDoubleSpinBox()
        self.ck_sim.setRange(0.0, 100.0)
        self.ck_sim.setSingleStep(5.0)
        self.ck_sim.setSuffix(" %")
        self.ck_blend = QDoubleSpinBox()
        self.ck_blend.setRange(0.0, 100.0)
        self.ck_blend.setSingleStep(5.0)
        self.ck_blend.setSuffix(" %")
        self.ck_spill = QCheckBox("Farbsaum entfernen")
        form.addRow("Toleranz", self.ck_sim)
        form.addRow("Weiche Kante", self.ck_blend)
        form.addRow(self.ck_spill)
        bgrow = QHBoxLayout()
        self.ck_bg_label = QLabel("Hintergrund: schwarz")
        self.ck_bg_label.setStyleSheet(f"color: {MUTED};")
        self.ck_bg_btn = QPushButton("Hintergrund wählen …")
        self.ck_bg_clear = QPushButton("Entfernen")
        self.ck_prev = QPushButton("Vorschau …")
        self.ck_prev.setToolTip("Zeigt ein Bild aus der Mitte des Clips mit Key und Hintergrund, so wie es im Export aussieht.")
        bgrow.addWidget(self.ck_bg_btn)
        bgrow.addWidget(self.ck_bg_clear)
        form.addRow(bgrow)
        form.addRow(self.ck_prev)
        form.addRow(self.ck_bg_label)
        self.ck_on.toggled.connect(self._on_ck_toggle)
        self.ck_green.clicked.connect(lambda *_: self._set_ck_color("#00ff00"))
        self.ck_blue.clicked.connect(lambda *_: self._set_ck_color("#0000ff"))
        self.ck_pick.clicked.connect(self._pick_ck_color)
        self.ck_eye.clicked.connect(self._pick_ck_from_frame)
        self.ck_sim.valueChanged.connect(self._on_ck_field)
        self.ck_blend.valueChanged.connect(self._on_ck_field)
        self.ck_spill.toggled.connect(self._on_ck_field)
        self.ck_bg_btn.clicked.connect(self._pick_ck_bg)
        self.ck_bg_clear.clicked.connect(self._clear_ck_bg)
        self.ck_prev.clicked.connect(lambda *_: self.show_key_preview())
        self.clip_trans = QComboBox()
        self.clip_trans.addItem("– harter Schnitt –", "")
        for t in presets.load("transitions"):
            self.clip_trans.addItem(t["name"], t["id"])
        self.clip_trans.currentIndexChanged.connect(self._on_clip_field)
        self.clip_trans_dur = QDoubleSpinBox()
        self.clip_trans_dur.setRange(0.1, 5.0)
        self.clip_trans_dur.setSingleStep(0.1)
        self.clip_trans_dur.setSuffix(" s")
        self.clip_trans_dur.setValue(0.8)
        self.clip_trans_dur.valueChanged.connect(self._on_clip_field)
        btn_all = QPushButton("Diesen Übergang auf alle Clips anwenden")
        btn_all.clicked.connect(self.apply_transition_to_all)
        self.clip_trans_note = QLabel("Der letzte Clip hat keinen Übergang (es folgt kein weiterer Clip).")
        self.clip_trans_note.setWordWrap(True)
        self.clip_trans_note.setStyleSheet(f"color: {MUTED};")
        self.btn_silence = QPushButton("Stille entfernen …")
        self.btn_silence.setToolTip("Findet Pausen im Ton und schneidet sie heraus (Jump-Cut). Zuerst gibt es eine Vorschau mit Zahlen.")
        self.btn_silence.clicked.connect(lambda *_: self.remove_silence())
        self.btn_scenes = QPushButton("An Szenenwechseln teilen …")
        self.btn_scenes.setToolTip("Findet Stellen, an denen sich das Bild stark ändert, und teilt den Clip dort. Zuerst gibt es eine Vorschau mit Zahlen.")
        self.btn_scenes.clicked.connect(lambda *_: self.split_scenes())
        form.addRow(QLabel("Schneiden"))
        form.addRow(self.btn_silence)
        form.addRow(self.btn_scenes)
        form.addRow(QLabel("Übergang zum nächsten Clip"))
        form.addRow("Art", self.clip_trans)
        form.addRow("Dauer", self.clip_trans_dur)
        form.addRow(btn_all)
        form.addRow(self.clip_trans_note)
        self.clip_tab = w
        w.setEnabled(False)
        return w

    def _fix_slider(self, handler) -> tuple[QSlider, QLabel, QHBoxLayout]:
        """Regler 0 (aus) … 100 für „Rauschen entfernen“ / „Sprache klarer“."""
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(0, 100)
        sl.setValue(0)
        sl.valueChanged.connect(handler)
        lab = QLabel("aus")
        lab.setFixedWidth(48)
        row = QHBoxLayout()
        row.addWidget(sl, 1)
        row.addWidget(lab)
        return sl, lab, row

    @staticmethod
    def _fix_text(v: int) -> str:
        return f"{int(v)} %" if v else "aus"

    def _build_audio_tab(self) -> QWidget:
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        ov.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)

        # --- gewählter Audioblock
        self.aud_group = QGroupBox("Gewählter Audioblock")
        form = QFormLayout(self.aud_group)
        self.aud_name = QLabel("Kein Audioblock gewählt – in der Timeline anklicken")
        self.aud_name.setWordWrap(True)
        form.addRow(self.aud_name)
        self.aud_track = QComboBox()
        for t in (1, 2, 3):
            self.aud_track.addItem(TRACK_NAMES[t], t)
        self.aud_track.currentIndexChanged.connect(self._on_audio_field)
        form.addRow("Spur", self.aud_track)

        def dspin(lo, hi, step, suffix=" s", prefix=""):
            sp = QDoubleSpinBox()
            sp.setDecimals(2)
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            if suffix:
                sp.setSuffix(suffix)
            if prefix:
                sp.setPrefix(prefix)
            sp.valueChanged.connect(self._on_audio_field)
            return sp

        self.aud_start = dspin(0.0, 36000.0, 0.1)
        self.aud_in = dspin(0.0, 36000.0, 0.1)
        self.aud_out = dspin(0.05, 36000.0, 0.1)
        self.aud_speed = dspin(0.1, 20.0, 0.25, suffix="", prefix="× ")
        self.aud_speed.blockSignals(True)   # die Regler dahinter existieren noch nicht
        self.aud_speed.setValue(1.0)
        self.aud_speed.blockSignals(False)
        self.aud_fin = dspin(0.0, 60.0, 0.1)
        self.aud_fout = dspin(0.0, 60.0, 0.1)
        form.addRow("Start auf der Timeline", self.aud_start)
        form.addRow("Von (in der Datei)", self.aud_in)
        form.addRow("Bis (in der Datei)", self.aud_out)
        form.addRow("Geschwindigkeit", self.aud_speed)
        self.aud_vol = QSlider(Qt.Orientation.Horizontal)
        self.aud_vol.setRange(0, 200)
        self.aud_vol.setValue(100)
        self.aud_vol.valueChanged.connect(self._on_audio_field)
        self.aud_vol_label = QLabel("100 %")
        vr = QHBoxLayout()
        vr.addWidget(self.aud_vol, 1)
        vr.addWidget(self.aud_vol_label)
        form.addRow("Lautstärke", vr)
        self.aud_dn, self.aud_dn_label, dnr = self._fix_slider(self._on_audio_field)
        self.aud_vc, self.aud_vc_label, vcr = self._fix_slider(self._on_audio_field)
        form.addRow("Rauschen entfernen", dnr)
        form.addRow("Sprache klarer", vcr)
        form.addRow("Einblenden", self.aud_fin)
        form.addRow("Ausblenden", self.aud_fout)
        self.aud_loop = QCheckBox("Wiederholen, bis das Video endet")
        self.aud_mute = QCheckBox("Stummschalten")
        self.aud_rev = QCheckBox("Rückwärts")
        for cb in (self.aud_loop, self.aud_mute, self.aud_rev):
            cb.toggled.connect(self._on_audio_field)
            form.addRow(cb)
        self.btn_beats = QPushButton("Beats erkennen …")
        self.btn_beats.setToolTip("Tempo der Musik finden, Marker auf die Schläge setzen und/oder Clips auf den Beat schneiden.")
        self.btn_beats.clicked.connect(lambda *_: self.detect_beats())
        form.addRow(self.btn_beats)
        self.btn_aud_reattach = QPushButton("Wieder mit dem Video verbinden")
        self.btn_aud_reattach.clicked.connect(self.reattach_selected_audio)
        form.addRow(self.btn_aud_reattach)
        self.btn_aud_remove = QPushButton("Audioblock löschen")
        self.btn_aud_remove.clicked.connect(self.remove_audio)
        form.addRow(self.btn_aud_remove)
        self.aud_group.setEnabled(False)
        v.addWidget(self.aud_group)

        # --- Hinzufügen
        gb = QGroupBox("Ton hinzufügen")
        gl = QVBoxLayout(gb)
        b1 = QPushButton("Ton vom gewählten Clip trennen")
        b1.clicked.connect(self.detach_selected_audio)
        b2 = QPushButton("Ton wieder mit gewähltem Clip verbinden")
        b2.clicked.connect(self.reattach_selected_clip)
        b3 = QPushButton("Musik / Audio hinzufügen …")
        b3.clicked.connect(self.add_audio_dialog)
        for b in (b1, b2, b3):
            gl.addWidget(b)
        hint = QLabel("Spuren: A1 Ton (Sprache), A2 Musik, A3 frei. Blöcke lassen sich in der Timeline mit der "
                      "Maus verschieben (Ränder = kürzen) und rasten an Clipgrenzen ein.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED};")
        gl.addWidget(hint)
        v.addWidget(gb)

        # --- Mischpult
        mix = QGroupBox("Mischpult")
        mf = QFormLayout(mix)
        self._mix_sliders: dict[int, QSlider] = {}
        self._mix_labels: dict[int, QLabel] = {}
        self._mix_mutes: dict[int, QCheckBox] = {}
        for t in (1, 2, 3):
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 200)
            sl.setValue(100)
            sl.valueChanged.connect(self._on_mix_field)
            lab = QLabel("100 %")
            lab.setFixedWidth(48)
            mu = QCheckBox("stumm")
            mu.toggled.connect(self._on_mix_field)
            row = QHBoxLayout()
            row.addWidget(sl, 1)
            row.addWidget(lab)
            row.addWidget(mu)
            mf.addRow(TRACK_NAMES[t], row)
            self._mix_sliders[t], self._mix_labels[t], self._mix_mutes[t] = sl, lab, mu
        self.mix_duck = QCheckBox("Musik automatisch leiser, wenn Ton spricht (Ducking)")
        self.mix_duck.toggled.connect(self._on_mix_field)
        mf.addRow(self.mix_duck)
        self.mix_duck_amount = QSlider(Qt.Orientation.Horizontal)
        self.mix_duck_amount.setRange(0, 100)
        self.mix_duck_amount.setValue(60)
        self.mix_duck_amount.valueChanged.connect(self._on_mix_field)
        self.mix_duck_label = QLabel("60 %")
        dr = QHBoxLayout()
        dr.addWidget(self.mix_duck_amount, 1)
        dr.addWidget(self.mix_duck_label)
        mf.addRow("Stärke", dr)
        self.mix_norm = QCheckBox("Lautheit angleichen")
        self.mix_norm.toggled.connect(self._on_mix_field)
        self.mix_lufs = QComboBox()
        for val, label in ((-14.0, "−14 LUFS (YouTube, TikTok, Shorts)"), (-16.0, "−16 LUFS (Podcast, Instagram)"),
                           (-23.0, "−23 LUFS (Fernsehen, EBU R128)")):
            self.mix_lufs.addItem(label, val)
        self.mix_lufs.currentIndexChanged.connect(self._on_mix_field)
        mf.addRow(self.mix_norm)
        mf.addRow("Ziel", self.mix_lufs)
        v.addWidget(mix)
        v.addStretch(1)
        return outer

    def _build_overlay_tab(self) -> QWidget:
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        ov.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)

        b0 = QPushButton("Bild-in-Bild hinzufügen …")
        b0.clicked.connect(self.add_overlay_dialog)
        v.addWidget(b0)
        hint = QLabel("Legt ein Video oder Bild über das Hauptvideo (Spur V2): Reaktionsvideo, Logo, Sticker. "
                      "Der Block in der Timeline lässt sich verschieben und an den Rändern kürzen. "
                      "Zu sehen ist es in „Vorschau mit Effekten“ und im Export.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED};")
        v.addWidget(hint)

        self.ov_group = QGroupBox("Gewähltes Bild-in-Bild")
        form = QFormLayout(self.ov_group)
        self.ov_name = QLabel("Keins gewählt – in der Timeline anklicken")
        self.ov_name.setWordWrap(True)
        form.addRow(self.ov_name)

        def dspin(lo, hi, step, suffix=" s", prefix=""):
            sp = QDoubleSpinBox()
            sp.setDecimals(2)
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            if suffix:
                sp.setSuffix(suffix)
            if prefix:
                sp.setPrefix(prefix)
            sp.valueChanged.connect(self._on_overlay_field)
            return sp

        self.ov_start = dspin(0.0, 36000.0, 0.1)
        self.ov_in = dspin(0.0, 36000.0, 0.1)
        self.ov_out = dspin(0.05, IMAGE_MAX, 0.1)
        self.ov_speed = dspin(0.1, 20.0, 0.25, suffix="", prefix="× ")
        self.ov_speed.blockSignals(True)
        self.ov_speed.setValue(1.0)
        self.ov_speed.blockSignals(False)
        form.addRow("Start auf der Timeline", self.ov_start)
        form.addRow("Von (in der Datei)", self.ov_in)
        form.addRow("Bis / Dauer", self.ov_out)
        form.addRow("Geschwindigkeit", self.ov_speed)
        self.ov_corner = QComboBox()
        for key, name in (("", "– frei –"), ("tr", "Oben rechts"), ("tl", "Oben links"), ("br", "Unten rechts"),
                          ("bl", "Unten links"), ("c", "Mitte")):
            self.ov_corner.addItem(name, key)
        self.ov_corner.currentIndexChanged.connect(self._on_overlay_corner)
        form.addRow("Position", self.ov_corner)
        self.ov_x = dspin(0.0, 100.0, 1.0, suffix=" %")
        self.ov_y = dspin(0.0, 100.0, 1.0, suffix=" %")
        self.ov_size = dspin(5.0, 100.0, 1.0, suffix=" %")
        self.ov_opacity = dspin(0.0, 100.0, 5.0, suffix=" %")
        self.ov_rot = dspin(-720.0, 720.0, 5.0, suffix=" °")
        self.ov_fin = dspin(0.0, 30.0, 0.1)
        self.ov_fout = dspin(0.0, 30.0, 0.1)
        form.addRow("Mitte waagerecht", self.ov_x)
        form.addRow("Mitte senkrecht", self.ov_y)
        form.addRow("Größe (Breite)", self.ov_size)
        form.addRow("Deckkraft", self.ov_opacity)
        form.addRow("Drehung", self.ov_rot)
        form.addRow("Einblenden", self.ov_fin)
        form.addRow("Ausblenden", self.ov_fout)
        self.ov_border = QCheckBox("Weißer Rahmen")
        self.ov_border.toggled.connect(self._on_overlay_field)
        form.addRow(self.ov_border)
        self.ov_reverse = QCheckBox("Rückwärts abspielen (Bild und Ton)")
        self.ov_reverse.toggled.connect(self._on_overlay_field)
        form.addRow(self.ov_reverse)
        self.ov_sound = QCheckBox("Ton des Videos mitspielen")
        self.ov_sound.toggled.connect(self._on_overlay_field)
        self.ov_volume = dspin(0.0, 200.0, 5.0)
        self.ov_volume.setValue(100.0)
        self.ov_volume.setSuffix(" %")
        form.addRow(self.ov_sound)
        form.addRow("Lautstärke", self.ov_volume)
        self.ov_split_note = QLabel("Dieser Block liegt in einem Split-Feld (Reiter „Split“). Position, Größe und Rahmen "
                                    "gelten dort nicht.")
        self.ov_split_note.setWordWrap(True)
        self.ov_split_note.setStyleSheet(f"color: {MUTED};")
        self.ov_split_note.setVisible(False)
        form.addRow(self.ov_split_note)
        self.ov_cz = dspin(100.0, 400.0, 10.0)
        self.ov_cz.setSuffix(" %")
        self.ov_cdx = dspin(-100.0, 100.0, 5.0)
        self.ov_cdy = dspin(-100.0, 100.0, 5.0)
        for wdg in (self.ov_cz, self.ov_cdx, self.ov_cdy):
            wdg.valueChanged.connect(self._on_overlay_field)
        form.addRow("Ausschnitt: Zoom (Split)", self.ov_cz)
        form.addRow("Ausschnitt: nach rechts", self.ov_cdx)
        form.addRow("Ausschnitt: nach unten", self.ov_cdy)

        # Chroma-Key (Greenscreen): Hintergrundfarbe transparent machen
        self.ov_key_on = QCheckBox("Chroma-Key: Hintergrundfarbe entfernen (Greenscreen)")
        form.addRow(self.ov_key_on)
        krow = QHBoxLayout()
        self.ov_key_swatch = QLabel("")
        self.ov_key_swatch.setFixedSize(28, 18)
        self.ov_key_green = QPushButton("Grün")
        self.ov_key_blue = QPushButton("Blau")
        self.ov_key_eye = QPushButton("Pipette …")
        self.ov_key_eye.setToolTip("Ein Bild des Videos zeigen und die Farbe per Klick wählen")
        self.ov_key_pick = QPushButton("Andere Farbe …")
        krow.addWidget(self.ov_key_swatch)
        krow.addWidget(self.ov_key_green)
        krow.addWidget(self.ov_key_blue)
        krow.addWidget(self.ov_key_eye)
        krow.addWidget(self.ov_key_pick, 1)
        form.addRow("Schlüsselfarbe", krow)
        self.ov_key_sim = dspin(0.0, 100.0, 5.0, suffix=" %")
        self.ov_key_blend = dspin(0.0, 100.0, 5.0, suffix=" %")
        self.ov_key_spill = QCheckBox("Farbsaum entfernen (Grün/Blau an den Rändern)")
        form.addRow("Toleranz", self.ov_key_sim)
        form.addRow("Weiche Kante", self.ov_key_blend)
        form.addRow(self.ov_key_spill)
        self.ov_key_full = QPushButton("Als Vollbild darüberlegen (Mitte, 100 %)")
        form.addRow(self.ov_key_full)
        # Signale erst verbinden, wenn alle Felder existieren
        self.ov_key_on.toggled.connect(self._on_key_toggle)
        self.ov_key_green.clicked.connect(lambda *_: self._set_key_color("#00ff00"))
        self.ov_key_blue.clicked.connect(lambda *_: self._set_key_color("#0000ff"))
        self.ov_key_pick.clicked.connect(self._pick_key_color)
        self.ov_key_eye.clicked.connect(self._pick_key_from_frame)
        self.ov_key_spill.toggled.connect(self._on_overlay_field)
        self.ov_key_full.clicked.connect(self._overlay_fullscreen)
        self._build_overlay_motion(form)
        b1 = QPushButton("Bild-in-Bild löschen")
        b1.clicked.connect(self.remove_overlay)
        form.addRow(b1)
        self.ov_group.setEnabled(False)
        v.addWidget(self.ov_group)
        v.addStretch(1)
        return outer

    def _build_overlay_motion(self, form: QFormLayout) -> None:
        """Keyframes für Position, Größe und Deckkraft des gewählten Bild-in-Bild-Blocks."""
        head = QLabel("Bewegung über die Zeit (Keyframes)")
        head.setStyleSheet("font-weight: bold;")
        form.addRow(head)
        self.ov_kf_note = QLabel("")
        self.ov_kf_note.setWordWrap(True)
        self.ov_kf_note.setStyleSheet(f"color: {MUTED};")
        form.addRow(self.ov_kf_note)
        self.ov_kf_preset = QComboBox()
        self.ov_kf_preset.addItem("Vorlage wählen …", "")
        for key, label in overlaykeys.PRESETS.items():
            self.ov_kf_preset.addItem(label, key)
        self.ov_kf_apply = QPushButton("Anwenden")
        self.ov_kf_apply.setToolTip("Setzt Keyframes aus Position, Größe und Deckkraft des Blocks; danach änderbar")
        row = QHBoxLayout()
        row.addWidget(self.ov_kf_preset, 1)
        row.addWidget(self.ov_kf_apply)
        form.addRow(row)
        self.ov_kf_pick = QComboBox()
        form.addRow("Punkt", self.ov_kf_pick)

        def sp(lo, hi, step, suffix=" %"):
            w_ = QDoubleSpinBox()
            w_.setDecimals(1)
            w_.setRange(lo, hi)
            w_.setSingleStep(step)
            w_.setSuffix(suffix)
            w_.valueChanged.connect(self._on_ovk_field)
            return w_

        lim = overlaykeys.LIMITS
        self.ov_kf_t = sp(0.0, 100.0, 5.0)
        self.ov_kf_x = sp(*lim["x"], 1.0)
        self.ov_kf_y = sp(*lim["y"], 1.0)
        self.ov_kf_size = sp(*lim["size"], 1.0)
        self.ov_kf_op = sp(*lim["opacity"], 5.0)
        self.ov_kf_rot = sp(*lim["rot"], 5.0, " °")
        form.addRow("Zeit im Block", self.ov_kf_t)
        form.addRow("Mitte waagerecht", self.ov_kf_x)
        form.addRow("Mitte senkrecht", self.ov_kf_y)
        form.addRow("Größe (Breite)", self.ov_kf_size)
        form.addRow("Deckkraft", self.ov_kf_op)
        form.addRow("Drehung", self.ov_kf_rot)
        self.ov_anim_ease = QCheckBox("Sanfte Übergänge zwischen den Punkten")
        self.ov_anim_ease.toggled.connect(self._on_ovk_ease)
        form.addRow(self.ov_anim_ease)
        self.ov_kf_add = QPushButton("+ Punkt am Abspielkopf")
        self.ov_kf_add.setToolTip("Oder: Doppelklick auf den Block in der Timeline")
        self.ov_kf_del = QPushButton("Punkt löschen")
        self.ov_kf_prev = QPushButton("◀ Vorheriger")
        self.ov_kf_next = QPushButton("Nächster ▶")
        self.ov_kf_clear = QPushButton("Alle Keyframes löschen")
        r1 = QHBoxLayout()
        r1.addWidget(self.ov_kf_add)
        r1.addWidget(self.ov_kf_del)
        form.addRow(r1)
        r2 = QHBoxLayout()
        r2.addWidget(self.ov_kf_prev)
        r2.addWidget(self.ov_kf_next)
        form.addRow(r2)
        form.addRow(self.ov_kf_clear)
        self.ov_kf_pick.currentIndexChanged.connect(self._on_ovk_pick)
        self.ov_kf_apply.clicked.connect(self._apply_ovk_preset)
        self.ov_kf_add.clicked.connect(lambda *_: self.add_overlay_key())
        self.ov_kf_del.clicked.connect(self.remove_overlay_key)
        self.ov_kf_clear.clicked.connect(self.clear_overlay_keys)
        self.ov_kf_prev.clicked.connect(lambda *_: self._goto_overlay_key(-1))
        self.ov_kf_next.clicked.connect(lambda *_: self._goto_overlay_key(1))
        self.timeline.overlay_key_requested.connect(self._on_overlay_key_requested)

    def _show_ovk(self, o, select: int = -1) -> None:
        """Zeigt die Keyframes des Blocks in den Feldern (ruft keine Handler auf)."""
        was = self._loading
        self._loading = True
        keys = overlaykeys.clean(o.keys, o)
        active = overlaykeys.active(o)
        in_split = splitlib.is_split(o)
        cur = select if select >= 0 else max(0, self.ov_kf_pick.currentIndex())
        self.ov_kf_pick.clear()
        for i, k in enumerate(keys):
            self.ov_kf_pick.addItem(f"{i + 1}  –  bei {k['t'] * 100:.0f} %")
        cur = min(cur, len(keys) - 1)
        if cur >= 0:
            self.ov_kf_pick.setCurrentIndex(cur)
        k = keys[cur] if 0 <= cur < len(keys) else None
        for w_, f in ((self.ov_kf_x, "x"), (self.ov_kf_y, "y"), (self.ov_kf_size, "size"), (self.ov_kf_op, "opacity"),
                      (self.ov_kf_rot, "rot")):
            w_.setValue(k[f] if k else getattr(o, {"x": "x_pct", "y": "y_pct", "size": "size_pct", "opacity": "opacity", "rot": "rot"}[f]))
        self.ov_kf_t.setValue((k["t"] if k else 0.0) * 100.0)
        self.ov_anim_ease.setChecked(bool(o.anim_ease))
        for w_ in (self.ov_kf_pick, self.ov_kf_t, self.ov_kf_x, self.ov_kf_y, self.ov_kf_size, self.ov_kf_op, self.ov_kf_rot, self.ov_kf_del,
                   self.ov_kf_clear, self.ov_kf_prev, self.ov_kf_next, self.ov_anim_ease):
            w_.setEnabled(active and not in_split)
        self.ov_kf_add.setEnabled(not in_split)
        self.ov_kf_preset.setEnabled(not in_split)
        self.ov_kf_apply.setEnabled(not in_split)
        # feste Werte werden von den Keyframes überstimmt
        for w_ in (self.ov_x, self.ov_y, self.ov_size, self.ov_opacity, self.ov_corner, self.ov_rot):
            w_.setEnabled(not in_split and not active)
        if in_split:
            self.ov_kf_note.setText("Im Split-Feld gibt es keine Keyframes.")
        elif active:
            self.ov_kf_note.setText("Aktiv: Position, Größe, Deckkraft und Drehung kommen aus den Keyframes (Rauten im Block in der Timeline).")
        else:
            self.ov_kf_note.setText("Aus. Eine Vorlage wählen, „+ Punkt“ drücken oder den Block in der Timeline doppelklicken.")
        self._loading = was

    def _refresh_ovk(self, select: int = -1) -> None:
        o = self._selected_overlay()
        if o is None:
            return
        self._show_ovk(o, select)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _on_ovk_pick(self, *_a) -> None:
        o = self._selected_overlay()
        if self._loading or o is None:
            return
        self._show_ovk(o)

    def _on_ovk_field(self, *_a) -> None:
        o = self._selected_overlay()
        i = self.ov_kf_pick.currentIndex()
        if self._loading or o is None or i < 0:
            return
        overlaykeys.set_key(o, i, t=self.ov_kf_t.value() / 100.0, x=self.ov_kf_x.value(), y=self.ov_kf_y.value(),
                            size=self.ov_kf_size.value(), opacity=self.ov_kf_op.value(), rot=self.ov_kf_rot.value())
        t_new = self.ov_kf_t.value() / 100.0              # die Liste ist sortiert: Punkt über seine Zeit wiederfinden
        keys = overlaykeys.clean(o.keys, o)
        j = min(range(len(keys)), key=lambda n: abs(keys[n]["t"] - t_new)) if keys else -1
        self._refresh_ovk(j)

    def _on_ovk_ease(self, on: bool) -> None:
        o = self._selected_overlay()
        if self._loading or o is None:
            return
        o.anim_ease = bool(on)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _apply_ovk_preset(self) -> None:
        o = self._selected_overlay()
        key = self.ov_kf_preset.currentData()
        if o is None or not key:
            self.statusBar().showMessage("Zuerst einen Bild-in-Bild-Block anklicken und eine Vorlage wählen.")
            return
        if overlaykeys.active(o):
            o.keys = []                 # Vorlage geht von den festen Werten aus
        if overlaykeys.apply_preset(key, o):
            self._refresh_ovk(0)
            self._load_overlay_fields()

    def add_overlay_key(self, rel: float | None = None) -> None:
        o = self._selected_overlay()
        if o is None:
            self.statusBar().showMessage("Zuerst ein Bild-in-Bild in der Timeline anklicken.")
            return
        if splitlib.is_split(o):
            self.statusBar().showMessage("Im Split-Feld gibt es keine Keyframes.")
            return
        if rel is None:
            t = self.timeline.playhead if self.timeline.playhead >= 0 else o.start
            rel = (t - o.start) / max(o.length, 0.05)
        i = overlaykeys.add_key(o, max(0.0, min(1.0, rel)))
        self._refresh_ovk(i)
        self._load_overlay_fields()

    def _on_overlay_key_requested(self, idx: int, rel: float) -> None:
        if idx == self.osel:
            self.add_overlay_key(rel)

    def remove_overlay_key(self) -> None:
        o = self._selected_overlay()
        if o is None or not overlaykeys.remove_key(o, self.ov_kf_pick.currentIndex()):
            return
        self._refresh_ovk(0)
        self._load_overlay_fields()

    def clear_overlay_keys(self) -> None:
        o = self._selected_overlay()
        if o is None:
            return
        o.keys = []
        self._refresh_ovk(0)
        self._load_overlay_fields()

    def _goto_overlay_key(self, step: int) -> None:
        """Springt mit dem Abspielkopf zum vorherigen/nächsten Keyframe des gewählten Blocks."""
        o = self._selected_overlay()
        if o is None or not overlaykeys.active(o):
            return
        times = [o.start + k["t"] * o.length for k in overlaykeys.clean(o.keys, o)]
        now = self.timeline.playhead if self.timeline.playhead >= 0 else 0.0
        cand = [t for t in times if t > now + 0.02] if step > 0 else [t for t in times if t < now - 0.02]
        if not cand:
            return
        target = min(cand) if step > 0 else max(cand)
        keep = self.osel
        self._seek_project(target)                       # das Springen wählt sonst den Hauptclip und hebt die Auswahl auf
        self.osel = keep
        self._load_overlay_fields()
        self._show_ovk(o, times.index(target))
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _build_subtitle_tab(self) -> QWidget:
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        ov.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)

        self.sub_list = QListWidget()
        self.sub_list.setMinimumHeight(150)
        self.sub_list.currentRowChanged.connect(self._on_sub_selected)
        v.addWidget(self.sub_list)
        r = QHBoxLayout()
        for text, slot in (("+ Eintrag", self.add_subtitle), ("Entfernen", self.remove_subtitle),
                           ("Alle löschen", self.clear_subtitles)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            r.addWidget(b)
        v.addLayout(r)
        r2 = QHBoxLayout()
        for text, slot in (("SRT importieren …", self.import_srt), ("SRT speichern …", self.export_srt)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            r2.addWidget(b)
        v.addLayout(r2)

        self.sub_edit_box = QGroupBox("Gewählter Eintrag")
        f = QFormLayout(self.sub_edit_box)
        self.sub_text = QPlainTextEdit()
        self.sub_text.setMaximumHeight(70)
        self.sub_text.textChanged.connect(self._on_sub_field)
        self.sub_from = QDoubleSpinBox()
        self.sub_to = QDoubleSpinBox()
        for sp in (self.sub_from, self.sub_to):
            sp.setRange(0.0, 36000.0)
            sp.setSingleStep(0.1)
            sp.setSuffix(" s")
            sp.valueChanged.connect(self._on_sub_field)
        f.addRow("Text", self.sub_text)
        f.addRow("Von", self.sub_from)
        f.addRow("Bis", self.sub_to)
        self.sub_edit_box.setEnabled(False)
        v.addWidget(self.sub_edit_box)

        auto = QGroupBox("Automatisch aus Sprache")
        al = QVBoxLayout(auto)
        self.sub_lang = QComboBox()
        for key, name in ASR_LANGS:
            self.sub_lang.addItem(name, key)
        al.addWidget(self.sub_lang)
        self.btn_asr = QPushButton("Untertitel automatisch erzeugen")
        self.btn_asr.clicked.connect(self.auto_subtitles)
        al.addWidget(self.btn_asr)
        h = QLabel("Benötigt das kostenlose Programm whisper.cpp und ein Sprachmodell (einmalig, siehe README). "
                   "Alles läuft auf deinem PC, nichts wird hochgeladen.")
        h.setWordWrap(True)
        h.setStyleSheet(f"color: {MUTED};")
        al.addWidget(h)
        v.addWidget(auto)

        st = QGroupBox("Aussehen aller Untertitel")
        sf = QFormLayout(st)
        self.sub_font = QComboBox()
        self.sub_font.currentIndexChanged.connect(self._on_sub_style)
        self.sub_size = QDoubleSpinBox()
        self.sub_size.setRange(1.0, 20.0)
        self.sub_size.setSuffix(" % der Höhe")
        self.sub_size.setValue(5.5)
        self.sub_size.valueChanged.connect(self._on_sub_style)
        self.sub_pos = QComboBox()
        for key, label in TEXT_POS:
            self.sub_pos.addItem(label, key)
        self.sub_pos.setCurrentIndex(self.sub_pos.findData("bottom"))
        self.sub_pos.currentIndexChanged.connect(self._on_sub_style)
        self.sub_anim = QComboBox()
        for key, label in TEXT_ANIMS:
            if key in ("none", "fade", "slide_up", "bounce", "typewriter"):
                self.sub_anim.addItem(label, key)
        self.sub_anim.currentIndexChanged.connect(self._on_sub_style)
        self.sub_box = QCheckBox("Dunkler Kasten hinter dem Text")
        self.sub_box.toggled.connect(self._on_sub_style)
        self.btn_sub_color = QPushButton("Farbe wählen")
        self.btn_sub_color.clicked.connect(self.pick_sub_color)
        sf.addRow("Schrift", self.sub_font)
        sf.addRow("Größe", self.sub_size)
        sf.addRow("Position", self.sub_pos)
        sf.addRow("Animation", self.sub_anim)
        sf.addRow("Farbe", self.btn_sub_color)
        sf.addRow(self.sub_box)
        self.sub_karaoke = QCheckBox("Karaoke: gesprochenes Wort hervorheben")
        self.sub_karaoke.setToolTip("Jedes Wort wird zu seiner Zeit in der Hervorhebungsfarbe gezeigt. Die Wortzeiten werden "
                                    "aus der Länge der Wörter über die Dauer des Eintrags verteilt.")
        self.sub_karaoke.toggled.connect(self._on_sub_style)
        self.sub_kar_mode = QComboBox()
        for key, label in karaoke.MODES.items():
            self.sub_kar_mode.addItem(label, key)
        self.sub_kar_mode.currentIndexChanged.connect(self._on_sub_style)
        self.btn_sub_kar_color = QPushButton("Hervorhebungsfarbe wählen")
        self.btn_sub_kar_color.clicked.connect(self.pick_sub_kar_color)
        self.btn_sub_preview = QPushButton("Vorschau …")
        self.btn_sub_preview.setToolTip("Zeigt ein Bild mit Untertitel (gewählter Eintrag) so wie im Export")
        self.btn_sub_preview.clicked.connect(lambda *_: self.show_sub_preview())
        sf.addRow(self.sub_karaoke)
        sf.addRow("Karaoke-Art", self.sub_kar_mode)
        sf.addRow("Karaoke-Farbe", self.btn_sub_kar_color)
        sf.addRow(self.btn_sub_preview)
        v.addWidget(st)
        v.addStretch(1)
        self._refresh_sub_font_combo()
        return outer

    def _build_motion_tab(self) -> QWidget:
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        ov.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        self.motion_body = QWidget()
        mv = QVBoxLayout(self.motion_body)
        mv.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.motion_body)
        self.motion_name = QLabel("Zuerst einen Clip in der Timeline anklicken")
        self.motion_name.setWordWrap(True)
        mv.addWidget(self.motion_name)

        g1 = QGroupBox("Drehen, Spiegeln, Zuschneiden")
        f1 = QFormLayout(g1)
        rr = QHBoxLayout()
        for text, delta in (("↺ 90°", -90), ("↻ 90°", 90)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, d=delta: self._rotate_clip(d))
            rr.addWidget(b)
        f1.addRow("Drehen", rr)
        self.tf_flip_h = QCheckBox("Waagerecht spiegeln")
        self.tf_flip_v = QCheckBox("Senkrecht spiegeln")
        for cb in (self.tf_flip_h, self.tf_flip_v):
            cb.toggled.connect(self._on_transform_field)
            f1.addRow(cb)
        self.tf_crop: dict[str, QDoubleSpinBox] = {}
        for key, label in (("l", "Links abschneiden"), ("r", "Rechts abschneiden"),
                           ("t", "Oben abschneiden"), ("b", "Unten abschneiden")):
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 80.0)
            sp.setSingleStep(1.0)
            sp.setSuffix(" %")
            sp.valueChanged.connect(self._on_transform_field)
            self.tf_crop[key] = sp
            f1.addRow(label, sp)
        b_reset = QPushButton("Drehen/Zuschneiden zurücksetzen")
        b_reset.clicked.connect(self.reset_transform)
        f1.addRow(b_reset)
        mv.addWidget(g1)

        g2 = QGroupBox("Bewegung über die Zeit (Keyframes)")
        l2 = QVBoxLayout(g2)
        self.cmb_motion = QComboBox()
        self.cmb_motion.addItem("– Voreinstellung wählen –", "")
        for m in presets.load("motions"):
            self.cmb_motion.addItem(m["name"], m["id"])
        self.cmb_motion.currentIndexChanged.connect(self._on_motion_preset)
        l2.addWidget(self.cmb_motion)
        self.kf_list = QListWidget()
        self.kf_list.setMaximumHeight(120)
        self.kf_list.currentRowChanged.connect(self._on_kf_selected)
        l2.addWidget(self.kf_list)
        rb = QHBoxLayout()
        for text, slot in (("+ Keyframe", self.add_keyframe), ("Entfernen", self.remove_keyframe),
                           ("Bewegung löschen", self.clear_motion)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            rb.addWidget(b)
        l2.addLayout(rb)
        self.kf_box = QGroupBox("Gewählter Keyframe")
        f2 = QFormLayout(self.kf_box)
        self.kf_fields: dict[str, QDoubleSpinBox] = {}
        for key, label, lo, hi, suffix in (("t", "Zeitpunkt im Clip", 0.0, 100.0, " %"),
                                           ("zoom", "Zoom", 100.0, 400.0, " %"),
                                           ("x", "Schwenk waagerecht (−100 links … 100 rechts)", -100.0, 100.0, ""),
                                           ("y", "Schwenk senkrecht (−100 oben … 100 unten)", -100.0, 100.0, ""),
                                           ("rot", "Drehung", -45.0, 45.0, " °")):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(1)
            sp.setSingleStep(1.0)
            if suffix:
                sp.setSuffix(suffix)
            sp.valueChanged.connect(self._on_kf_field)
            self.kf_fields[key] = sp
            f2.addRow(label, sp)
        self.kf_box.setEnabled(False)
        l2.addWidget(self.kf_box)
        self.kf_ease = QCheckBox("Sanfte Übergänge zwischen den Keyframes")
        self.kf_ease.setChecked(True)
        self.kf_ease.toggled.connect(self._on_kf_field)
        l2.addWidget(self.kf_ease)
        b_all = QPushButton("Diese Bewegung auf alle Clips anwenden")
        b_all.clicked.connect(self.apply_motion_to_all)
        l2.addWidget(b_all)
        h = QLabel("Zoom 100 % = Originalgröße. Ab 101 % wird hineingezoomt; der Schwenk wirkt nur, wenn gezoomt wird. "
                   "Zu sehen ist die Bewegung in „Vorschau mit Effekten“ und im Export.")
        h.setWordWrap(True)
        h.setStyleSheet(f"color: {MUTED};")
        l2.addWidget(h)
        mv.addWidget(g2)
        v.addStretch(1)
        self.motion_body.setEnabled(False)
        return outer

    def _build_actions(self) -> None:
        def act(text, slot, shortcut=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            return a

        self.act_open = act("Projekt öffnen", self.open_project, "Ctrl+O")
        self.act_save = act("Projekt speichern", self.save_project, "Ctrl+S")
        self.act_preview = act("▶ Vorschau ab Abspielkopf (volle Qualität)", self.render_preview, "Ctrl+P")
        self.act_export = act("Exportieren …", self.export_video, "Ctrl+E")
        self.act_export_multi = act("Mehrere Formate exportieren …", self.export_multi, "Ctrl+Shift+E")
        self.act_undo = act("↶ Rückgängig", self.undo, "Ctrl+Z")
        self.act_redo = act("↷ Wiederholen", self.redo)
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])

        mf = self.menuBar().addMenu("Datei")
        mf.addAction(self.act_open)
        mf.addAction(self.act_save)
        mf.addSeparator()
        mf.addAction(act("Medien importieren …", self.import_dialog, "Ctrl+I"))
        mf.addSeparator()
        mf.addAction(self.act_preview)
        mf.addAction(self.act_export)
        mf.addAction(self.act_export_multi)
        self.act_export_gif = act("Als animiertes GIF exportieren …", self.export_gif)
        mf.addAction(self.act_export_gif)
        self.act_still = act("Aktuelles Bild als PNG speichern …", self.save_still)
        mf.addAction(self.act_still)
        mf.addSeparator()
        self.act_collect = act("Projekt sammeln (alle Dateien in einen Ordner oder ZIP) …", self.collect_project)
        mf.addAction(self.act_collect)

        # Name oben rechts in der Menüleiste (rot, wie das Logo)
        brand = QLabel(APP_NAME)
        f = QFont(getattr(self, "_brand_family", self.font().family()))
        f.setPointSize(13)
        brand.setFont(f)
        brand.setStyleSheet(f"color: {BRAND}; padding: 0 10px;")
        self.menuBar().setCornerWidget(brand, Qt.Corner.TopRightCorner)
        self._build_timeline_toolbar()

        me = self.menuBar().addMenu("Bearbeiten")
        me.addAction(self.act_undo)
        me.addAction(self.act_redo)
        me.addSeparator()
        self.act_dup = act("Auswahl duplizieren", self.duplicate_selected, "Ctrl+D")
        me.addAction(self.act_dup)
        me.addAction(act("Auswahl löschen", self.delete_selected))
        self.act_ripple = act("Löschen und Lücke schließen", self.ripple_delete_selected, "Ctrl+Delete")
        self.act_ripple.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        me.addAction(self.act_ripple)
        self.act_ripple_tracks = QAction("Beim Lücke-Schließen Bild-in-Bild, Ton und Effekte mitnehmen", self)
        self.act_ripple_tracks.setCheckable(True)
        self.act_ripple_tracks.setChecked(True)
        me.addAction(self.act_ripple_tracks)
        self.act_close_gaps = act("Alle Lücken auf den Zusatzspuren schließen", self.close_all_gaps)
        me.addAction(self.act_close_gaps)
        self.act_freeze = act("Standbild an dieser Stelle einfügen …", self.insert_freeze, "Ctrl+Shift+F")
        me.addAction(self.act_freeze)
        me.addSeparator()
        mk = me.addMenu("Marker")
        mk.addAction(act("Marker setzen / entfernen (M)", self.add_marker))
        mk.addAction(act("Zum nächsten Marker (Strg+→)", lambda: self.goto_marker(1)))
        mk.addAction(act("Zum vorherigen Marker (Strg+←)", lambda: self.goto_marker(-1)))
        mk.addAction(act("Marker benennen …", self.rename_marker))
        mk.addAction(act("Alle Marker entfernen", self.clear_markers))
        mk.addSeparator()
        mk.addAction(act("YouTube-Kapitel für die Beschreibung …", self.show_chapters))
        me.addSeparator()
        me.addAction(act("Fehlende Dateien suchen …", self.relink_dialog))

        m = self.menuBar().addMenu("Hilfe")
        m.addAction(act("Kurzanleitung", self.show_help, "F1"))
        m.addAction(act("Nach Updates suchen", lambda: self.check_updates(silent=False)))
        m.addAction(act("Eigene Presets-Ordner öffnen", self.open_presets_folder))
        m.addAction(act("Lizenzen und Drittanbieter-Software", self.show_licenses))
        m.addSeparator()
        m.addAction(act("Spracherkennung einrichten …", self.setup_whisper))
        m.addAction(act("Diagnose und Fehlerbericht …", self.show_diagnostics))
        m.addAction(act("Protokoll-Ordner öffnen", lambda: self._open_folder(str(diagnostics.log_dir()))))
        m.addSeparator()
        m.addAction(act("Über", self.about))

        self.act_play = act("Abspielen/Pause", self.toggle_play, "Space")
        self.addAction(self.act_play)
        self.act_del = act("Auswahl löschen", self.delete_selected, "Delete")
        self.act_del.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.timeline.addAction(self.act_del)
        self.timeline.addAction(self.act_ripple)

    # ---------------------------------------------------------- Presets & Sync
    def _populate_presets(self) -> None:
        self._loading = True
        self.cmb_format.clear()
        for p in presets.load("formats"):
            self.cmb_format.addItem(p["name"], p["id"])
        self.cmb_export.clear()
        for p in presets.load("exports"):
            self.cmb_export.addItem(p["name"], p["id"])
        self.cmb_grade.clear()
        self.cmb_grade.addItem("– Voreinstellung wählen –", "")
        for p in presets.load("grades"):
            self.cmb_grade.addItem(p["name"], p["id"])
        self.cmb_look.clear()
        self.cmb_look.addItem("– Look wählen –", "")
        for p in presets.load("looks"):
            self.cmb_look.addItem(p["name"], p["id"])
        self._loading = False

    def _sync_controls_from_project(self) -> None:
        self._loading = True
        p = self.project
        for combo, value in ((self.cmb_format, p.format_id), (self.cmb_export, p.export_id),
                             (self.cmb_layout, p.layout)):
            idx = combo.findData(value)
            combo.setCurrentIndex(max(0, idx))
        self.sp_fade_in.setValue(p.fade_in)
        self.sp_fade_out.setValue(p.fade_out)
        self._show_watermark()
        self._show_sub_export()
        # Effekte (Blöcke auf der FX-Spur)
        self.fsel = min(self.fsel, len(p.effects) - 1)
        # Texte
        self.text_list.clear()
        for t in p.texts:
            self.text_list.addItem(self._text_title(t))
        self._loading = False
        self._update_format_info()
        self._load_fx_fields()
        self._load_mix_fields()
        self._load_sub_list()
        self._load_sub_style()

    def _update_format_info(self) -> None:
        f = presets.get("formats", self.project.format_id)
        if f:
            self.format_info.setText(f"{f['width']}×{f['height']} px, {f.get('fps', 30)} fps. "
                                     f"Standard-Anpassung: {dict((k, v) for k, v in LAYOUTS)[f.get('layout', 'fit')]}.")

    # ------------------------------------------------------- Format-Handler
    def _on_format_changed(self) -> None:
        if self._loading:
            return
        self.project.format_id = self.cmb_format.currentData()
        f = presets.get("formats", self.project.format_id) or {}
        default_exp = f.get("default_export")
        if default_exp:
            idx = self.cmb_export.findData(default_exp)
            if idx >= 0:
                self._loading = True
                self.cmb_export.setCurrentIndex(idx)
                self._loading = False
                self.project.export_id = default_exp
        self._update_format_info()

    def _on_layout_changed(self) -> None:
        if not self._loading:
            self.project.layout = self.cmb_layout.currentData() or ""

    def _on_export_changed(self) -> None:
        if not self._loading:
            self.project.export_id = self.cmb_export.currentData()

    def _on_fades_changed(self) -> None:
        if not self._loading:
            self.project.fade_in = self.sp_fade_in.value()
            self.project.fade_out = self.sp_fade_out.value()

    def _show_watermark(self) -> None:
        p = self.project
        was = self._loading
        self._loading = True
        self.wm_name.setText(Path(p.watermark).name if p.watermark else "kein Logo")
        self.wm_corner.setCurrentIndex(max(0, self.wm_corner.findData(p.wm_corner)))
        self.wm_size.setValue(p.wm_size)
        self.wm_opacity.setValue(p.wm_opacity)
        for wdg in (self.wm_corner, self.wm_size, self.wm_opacity, self.wm_clear):
            wdg.setEnabled(bool(p.watermark))
        self._loading = was

    def _on_wm_changed(self, *_a) -> None:
        if self._loading:
            return
        self.project.wm_corner = self.wm_corner.currentData() or "br"
        self.project.wm_size = self.wm_size.value()
        self.project.wm_opacity = self.wm_opacity.value()

    def _show_sub_export(self) -> None:
        was = self._loading
        self._loading = True
        self.chk_sub_burn.setChecked(bool(self.project.sub_burn))
        self.chk_sub_srt.setChecked(bool(self.project.sub_srt))
        self._loading = was

    def _on_sub_export_changed(self, *_a) -> None:
        if self._loading:
            return
        self.project.sub_burn = self.chk_sub_burn.isChecked()
        self.project.sub_srt = self.chk_sub_srt.isChecked()

    def set_watermark(self, path: str) -> None:
        self.project.watermark = path
        self._show_watermark()
        self.statusBar().showMessage(f"Wasserzeichen: {Path(path).name}" if path else "Wasserzeichen entfernt.")

    def pick_watermark(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Logo oder Wasserzeichen wählen", "",
                                           "Bilder (*.png *.jpg *.jpeg *.webp *.bmp);;Alle Dateien (*)")
        if f:
            self.set_watermark(f)

    def clear_watermark(self) -> None:
        self.set_watermark("")

    # ------------------------------------------------------ Effekt-Handler
    def _on_look_chosen(self, _idx: int) -> None:
        look = presets.get("looks", self.cmb_look.currentData() or "")
        if not look:
            return
        out = []
        for entry in look.get("effects", []):
            eid, intensity = entry[0], entry[1]
            start = float(entry[2]) if len(entry) > 2 else 0.0
            end = float(entry[3]) if len(entry) > 3 else 0.0
            if eid not in fx.REGISTRY:
                continue
            e = {"id": eid, "intensity": intensity}
            if start > 0 or end > 0:
                e["start"] = start
                e["end"] = end if end > 0 else None
            out.append(e)
        self.project.effects = out
        self.project.look_id = look["id"]
        self.fsel = -1
        self._load_fx_fields()
        self._refresh_timeline_only()

    def _current_effect_id(self) -> str | None:
        item = self.fx_tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def add_effect_block(self, eid: str | None = None, at: float | None = None) -> None:
        """Legt einen Effekt-Block auf der FX-Spur an (Standard: gewählter Effekt, am Abspielkopf)."""
        eid = eid or self._current_effect_id()
        if not eid or eid not in fx.REGISTRY:
            self.statusBar().showMessage("Zuerst links einen Effekt aus der Liste wählen.")
            return
        if at is None:
            at = self.timeline.playhead if self.timeline.playhead >= 0 else 0.0
        i = self.project.fx_add(eid, fx.REGISTRY[eid].default, at)
        self.project.look_id = "none"
        self.fsel, self.asel, self.osel = i, -1, -1
        self._load_fx_fields()
        self._load_audio_fields()
        self._load_overlay_fields()
        self._refresh_timeline_only()
        self.statusBar().showMessage(f"Effekt „{fx.REGISTRY[eid].name}“ auf die FX-Spur gelegt – ziehen zum Verschieben.")

    def _on_fx_dropped(self, eid: str, t: float) -> None:
        self.add_effect_block(eid, t)
        self.tabs.setCurrentIndex(FX_TAB)

    def remove_effect_block(self) -> None:
        if not (0 <= self.fsel < len(self.project.effects)):
            self.statusBar().showMessage("Zuerst einen Effekt-Block in der Timeline anklicken.")
            return
        del self.project.effects[self.fsel]
        self.fsel = min(self.fsel, len(self.project.effects) - 1)
        self._load_fx_fields()
        self._refresh_timeline_only()

    def _select_fx(self, idx: int) -> None:
        self.fsel = idx
        self.asel = self.osel = -1
        self._load_audio_fields()
        self._load_overlay_fields()
        self._load_fx_fields()
        self.tabs.setCurrentIndex(FX_TAB)

    def _on_fx_edited(self, idx: int) -> None:
        if idx == self.fsel:
            self._load_fx_fields()

    def _load_fx_fields(self) -> None:
        ok = 0 <= self.fsel < len(self.project.effects)
        if self.view_stack.currentIndex() == 1 and self._mask_edit_idx != self.fsel:
            self._mask_edit_off()                 # anderer Block gewählt → Rahmen-Ansicht schließen
        self.fx_box.setEnabled(ok)
        self.btn_fx_del.setEnabled(ok)
        if not ok:
            self.fx_box.setTitle("Gewählter Effekt-Block (keiner gewählt – in der Timeline anklicken)")
            self.fx_mask_box.setVisible(False)
            if self.view_stack.currentIndex() == 1:
                self._mask_edit_off()
            return
        e = self.project.effects[self.fsel]
        s0, t0 = self.project.fx_span(self.fsel)
        whole_end = e.get("end") is None
        was = self._loading
        self._loading = True
        eff = fx.REGISTRY.get(e["id"])
        self.fx_box.setTitle(f"Gewählter Effekt-Block: {eff.name if eff else e['id']}")
        self.fx_int.setValue(int(e.get("intensity", 50)))
        self.fx_int_label.setText(str(int(e.get("intensity", 50))))
        self.fx_start.setValue(s0)
        self.fx_end.setValue(0.0 if whole_end else t0)
        is_mask = bool(eff and eff.params)
        self.fx_mask_box.setVisible(is_mask)
        if is_mask:
            m = fx.mask_params(e.get("mask"))
            self.mask_shape.setCurrentIndex(max(0, self.mask_shape.findData(m["shape"])))
            self.mask_x.setValue(m["x"])
            self.mask_y.setValue(m["y"])
            self.mask_w.setValue(m["w"])
            self.mask_h.setValue(m["h"])
            self.mask_feather.setValue(int(m["feather"]))
            self.mask_invert.setChecked(m["invert"])
            self._load_mask_info(e)
        elif self.view_stack.currentIndex() == 1:
            self._mask_edit_off()
        self._loading = was

    def _on_fx_param(self, *_args) -> None:
        self.fx_int_label.setText(str(self.fx_int.value()))
        if self._loading or not (0 <= self.fsel < len(self.project.effects)):
            return
        e = self.project.effects[self.fsel]
        e["intensity"] = self.fx_int.value()
        start = self.fx_start.value()
        end = self.fx_end.value()
        total = self.project.duration
        self.project.fx_set_span(self.fsel, start, end if end > 0 else (total if total > 0 else start + self.project.FX_MIN))
        self._refresh_timeline_only()

    def _on_mask_param(self, *_args) -> None:
        self._write_mask(clear_track=False)

    def _write_mask(self, clear_track: bool = False) -> None:
        if self._loading or not (0 <= self.fsel < len(self.project.effects)):
            return
        e = self.project.effects[self.fsel]
        eff = fx.REGISTRY.get(e["id"])
        if not (eff and eff.params):
            return
        old = fx.mask_params(e.get("mask"))
        e["mask"] = {"shape": self.mask_shape.currentData() or "ellipse", "x": self.mask_x.value(), "y": self.mask_y.value(),
                     "w": self.mask_w.value(), "h": self.mask_h.value(), "feather": float(self.mask_feather.value()),
                     "invert": self.mask_invert.isChecked(), "track": [] if clear_track else old["track"]}
        if self.view_stack.currentIndex() == 1:
            self.mask_canvas.set_mask(fx.mask_params(e["mask"]), e["mask"]["track"])
        self._load_mask_info(e)
        self._refresh_timeline_only()

    def _load_mask_info(self, e: dict) -> None:
        tr = fx.mask_params(e.get("mask"))["track"]
        self.mask_info.setText("Der Bereich bleibt an einer Stelle (Mitte in % des Bildes)." if not tr
                               else f"Der Bereich folgt einem Pfad ({len(tr)} Punkte). Rahmen verschieben entfernt den Pfad.")

    # -- Tracking
    def _track_start(self) -> None:
        if self._track_worker is not None:                      # läuft schon → abbrechen
            self._track_worker.cancel()
            return
        idx = self.fsel
        if not (0 <= idx < len(self.project.effects)):
            return
        e = self.project.effects[idx]
        eff = fx.REGISTRY.get(e["id"])
        if not (eff and eff.params):
            return
        self._track_target = e
        w = TrackWorker(copy.deepcopy(self.project), idx, self)
        self._track_worker = w
        self.btn_track.setText("Abbrechen")
        self.mask_info.setText("Verfolgen … 0 %")
        w.progress.connect(lambda p: self.mask_info.setText(f"Verfolgen … {int(p * 100)} %"))
        w.done.connect(self._track_done)
        w.start()

    def _track_done(self, res, err: str) -> None:
        self._track_worker = None
        self.btn_track.setText("Objekt verfolgen")
        e = self._track_target
        self._track_target = None
        if err:
            msg = "Verfolgen abgebrochen." if "Abgebrochen" in err else f"Verfolgen nicht möglich: {err[-160:]}"
            if "Abgebrochen" not in err:
                diagnostics.log_error("Tracking fehlgeschlagen: %s", err[-500:])
            self.statusBar().showMessage(msg)
            if e is not None and any(x is e for x in self.project.effects):
                self._load_mask_info(e)
            return
        if e is None or not any(x is e for x in self.project.effects):
            return
        m = fx.mask_params(e.get("mask"))
        if res.points:
            m["x"], m["y"] = res.points[0][1], res.points[0][2]
        m["track"] = res.points
        e["mask"] = m
        self._load_fx_fields()
        if self.view_stack.currentIndex() == 1:
            self.mask_canvas.set_mask(m, m["track"])
        self._refresh_timeline_only()
        note = f"{res.lost} von {res.frames} Bildern unsicher – Pfad prüfen" if res.lost > res.frames * 0.15 else "Pfad sieht gut aus"
        self.statusBar().showMessage(f"Verfolgt: {len(res.points)} Punkte über {res.seconds:.1f} s. {note}.")

    def _track_clear(self) -> None:
        if not (0 <= self.fsel < len(self.project.effects)):
            return
        e = self.project.effects[self.fsel]
        m = fx.mask_params(e.get("mask"))
        if not m["track"]:
            return
        m["track"] = []
        e["mask"] = m
        if self.view_stack.currentIndex() == 1:
            self.mask_canvas.set_mask(m, [])
        self._load_mask_info(e)
        self._refresh_timeline_only()

    # -- Rahmen im Vorschaubild
    def _mask_edit_toggled(self, on: bool) -> None:
        if not on:
            self._mask_edit_off()
            return
        eff = fx.REGISTRY.get(self.project.effects[self.fsel]["id"]) if 0 <= self.fsel < len(self.project.effects) else None
        if not (eff and eff.params):
            self._mask_edit_off()
            return
        self._mask_edit_idx = self.fsel
        s0, t0 = self.project.fx_span(self.fsel)
        t = min(max(self.timeline.playhead, s0), max(s0, t0 - 0.05))
        self._mask_frame_token = getattr(self, "_mask_frame_token", 0) + 1
        token = self._mask_frame_token
        self.mask_canvas.clear_frame()
        self.view_stack.setCurrentIndex(1)
        self.statusBar().showMessage("Bild wird geladen …")
        tmp = paths.user_dir() / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        png = str(tmp / f"maskframe_{uuid.uuid4().hex[:8]}.png")
        w = FrameWorker(copy.deepcopy(self.project), t, min(540, int(self.cmb_prev_q.currentData() or 360) * 3 // 2), png,
                        str(tmp), self)
        self._frame_workers.append(w)
        w.done.connect(lambda p, err, k=token, w=w: self._on_mask_frame(p, err, k, w))
        w.start()

    def _on_mask_frame(self, png: str, err: str, token: int, worker) -> None:
        if worker in self._frame_workers:
            self._frame_workers.remove(worker)
        if token != self._mask_frame_token or self.view_stack.currentIndex() != 1:
            _rm(png)
            return
        if err or not self.mask_canvas.set_frame(png):
            _rm(png)
            diagnostics.log_error("Maskenbild fehlgeschlagen: %s", err[-500:])
            self.statusBar().showMessage(f"Bild konnte nicht geladen werden: {err[-120:]}")
            self._mask_edit_off()
            return
        _rm(png)
        if 0 <= self.fsel < len(self.project.effects):
            m = fx.mask_params(self.project.effects[self.fsel].get("mask"))
            if m["track"]:                                    # Rahmen dort zeigen, wo der Pfad beginnt
                m["x"], m["y"] = m["track"][0][1], m["track"][0][2]
            self.mask_canvas.set_mask(m, m["track"])
        self.statusBar().showMessage("Rahmen in der Mitte verschieben, an Rändern und Ecken ziehen.")

    def _mask_edit_off(self) -> None:
        self._mask_frame_token = getattr(self, "_mask_frame_token", 0) + 1
        self.view_stack.setCurrentIndex(0)
        was = self.btn_mask_edit.blockSignals(True)
        self.btn_mask_edit.setChecked(False)
        self.btn_mask_edit.blockSignals(was)

    def _on_mask_canvas(self, m: dict) -> None:
        was = self._loading
        self._loading = True
        self.mask_x.setValue(float(m["x"]))
        self.mask_y.setValue(float(m["y"]))
        self.mask_w.setValue(float(m["w"]))
        self.mask_h.setValue(float(m["h"]))
        self._loading = was
        self._write_mask(clear_track=True)

    # --------------------------------------------------------- Text-Handler
    @staticmethod
    def _text_title(t: TextLayer) -> str:
        first = (t.text.strip().splitlines() or [""])[0]
        return (first[:28] + "…" if len(first) > 28 else first) or "(leer)"

    def _refresh_font_combo(self) -> None:
        cur = self.text_font.currentData()
        self.text_font.blockSignals(True)
        self.text_font.clear()
        for name, path in self._fonts.items():
            self.text_font.addItem(name, path)
        self.text_font.addItem("Standardschrift", "")
        idx = self.text_font.findData(cur) if cur is not None else 0
        self.text_font.setCurrentIndex(max(0, idx))
        self.text_font.blockSignals(False)

    def add_font(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Schriftdatei(en) wählen", "", "Schriften (*.ttf *.otf)")
        for f in files:
            shutil.copy(f, paths.user_fonts_dir() / Path(f).name)
        if files:
            self._load_fonts()
            self._refresh_font_combo()
            self._refresh_sub_font_combo()
            self.statusBar().showMessage(f"{len(files)} Schrift(en) hinzugefügt.")

    def add_text(self) -> None:
        font = self.text_font.itemData(0) or ""
        t = TextLayer(text="Dein Text", start=0.0, end=max(3.0, min(5.0, self.project.duration or 3.0)), font=font)
        self.project.texts.append(t)
        self.text_list.addItem(self._text_title(t))
        self.text_list.setCurrentRow(len(self.project.texts) - 1)

    def remove_text(self) -> None:
        row = self.text_list.currentRow()
        if 0 <= row < len(self.project.texts):
            del self.project.texts[row]
            self.text_list.takeItem(row)

    def _on_text_selected(self, row: int) -> None:
        if not (0 <= row < len(self.project.texts)):
            self.text_box.setEnabled(False)
            return
        t = self.project.texts[row]
        self._loading = True
        self.text_edit.setPlainText(t.text)
        self.text_pos.setCurrentIndex(max(0, self.text_pos.findData(t.position)))
        self.text_size.setValue(t.size_pct)
        self.text_start.setValue(t.start)
        self.text_end.setValue(t.end)
        idx = self.text_font.findData(paths.resolve_font(t.font))
        self.text_font.setCurrentIndex(idx if idx >= 0 else max(0, self.text_font.count() - 1))
        self._text_color = t.color if t.color.startswith("#") else "#ffffff"
        self._style_color_button()
        self.text_anim.setCurrentIndex(max(0, self.text_anim.findData(t.anim)))
        self.text_anim_dur.setValue(t.anim_dur)
        self.text_boxbg.setChecked(t.box)
        self._loading = False
        self.text_box.setEnabled(True)

    def _on_text_field(self, *_args) -> None:
        if self._loading:
            return
        row = self.text_list.currentRow()
        if not (0 <= row < len(self.project.texts)):
            return
        t = self.project.texts[row]
        t.text = self.text_edit.toPlainText()
        t.position = self.text_pos.currentData() or "bottom"
        t.size_pct = self.text_size.value()
        t.start, t.end = self.text_start.value(), self.text_end.value()
        t.font = self.text_font.currentData() or ""
        t.color = self._text_color
        t.anim = self.text_anim.currentData() or "none"
        t.anim_dur = self.text_anim_dur.value()
        t.box = self.text_boxbg.isChecked()
        item = self.text_list.item(row)
        if item:
            item.setText(self._text_title(t))
        miss = missing_chars(t.font, t.text)
        if miss:
            self.statusBar().showMessage(
                f"Achtung: Die gewählte Schrift hat keine Zeichen für: {' '.join(miss)} – sie bleiben im Video leer. "
                "Für diesen Text die „Standardschrift“ wählen oder die Zeichen ändern.")

    def pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._text_color), self, "Textfarbe")
        if c.isValid():
            self._text_color = c.name()
            self._style_color_button()
            self._on_text_field()

    def _style_color_button(self) -> None:
        self.btn_color.setStyleSheet(f"background: {self._text_color}; color: black; font-weight: 600;")

    # ------------------------------------------------------------- Medien
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.import_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def import_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Videos importieren", "", VIDEO_FILTER)
        self.import_files(files)

    def import_files(self, files: list[str]) -> None:
        errors = []
        for f in files:
            if f in self.media:
                continue
            try:
                info = probe(f)
                if info.duration <= 0:
                    raise ValueError("Keine Videolänge erkannt (Bilder werden noch nicht unterstützt).")
            except Exception as exc:  # noqa: BLE001
                try:                      # reine Audiodatei? Dann als Musik auf A2 legen
                    probe_audio(f)
                except Exception:  # noqa: BLE001
                    errors.append(f"{Path(f).name}: {exc}")
                else:
                    self.add_audio_files([f], track=2)
                continue
            self.media[f] = info
            kind = "Bild" if info.is_image else fmt_time(info.duration)
            it = QListWidgetItem(f"{Path(f).name}\n{kind}, {info.width}×{info.height}")
            it.setData(Qt.ItemDataRole.UserRole, f)
            it.setToolTip(f)
            self.media_list.addItem(it)
            self._start_thumb(f, info)
        self.media_hint.setVisible(self.media_list.count() == 0)
        if errors:
            QMessageBox.warning(self, "Import", "Nicht alle Dateien konnten gelesen werden:\n\n" + "\n".join(errors))
        if files and not self.project.clips and files[0] in self.media:
            self._add_to_timeline(files[0])

    def _start_thumb(self, path: str, info) -> None:
        w = ThumbWorker(path, info.duration, info.is_image, self)
        self._thumb_workers.append(w)
        w.done.connect(self._on_thumb)
        w.finished.connect(lambda w=w: self._thumb_workers.remove(w) if w in self._thumb_workers else None)
        w.start()

    def _on_thumb(self, src: str, png: str, err: str) -> None:
        if err or not png:
            return
        for i in range(self.media_list.count()):
            it = self.media_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == src:
                it.setIcon(QIcon(QPixmap(png)))
                break

    def _filter_media(self, text: str) -> None:
        q = (text or "").strip().lower()
        for i in range(self.media_list.count()):
            it = self.media_list.item(i)
            it.setHidden(bool(q) and q not in str(it.data(Qt.ItemDataRole.UserRole)).lower())

    def _on_media_selected(self, item, _prev) -> None:
        if item:
            self._open_media(item.data(Qt.ItemDataRole.UserRole), 0, None, autoplay=False)

    def _add_selected_media(self) -> None:
        it = self.media_list.currentItem()
        if it:
            self._add_to_timeline(it.data(Qt.ItemDataRole.UserRole))

    def _add_to_timeline(self, path: str, at: int | None = None) -> None:
        info = self.media.get(path)
        if not info:
            return
        if info.is_image:
            clip = Clip(path, IMAGE_MAX, out_pt=info.duration, has_audio=False, width=info.width,
                        height=info.height, is_image=True)
        else:
            clip = Clip(path, info.duration, has_audio=info.has_audio, width=info.width, height=info.height)
        pos = len(self.project.clips) if at is None else max(0, min(int(at), len(self.project.clips)))
        self.project.clips.insert(pos, clip)
        self._refresh_timeline(select=pos)

    # ------------------------------------------------------------ Timeline
    def _refresh_timeline(self, select: int | None = None) -> None:
        if select is not None:
            self.sel = select
        self.sel = min(self.sel, len(self.project.clips) - 1)
        self.project.sync_linked()
        if self.asel >= len(self.project.audio_clips):
            self.asel = len(self.project.audio_clips) - 1
        if self.osel >= len(self.project.overlays):
            self.osel = len(self.project.overlays) - 1
        if self.fsel >= len(self.project.effects):
            self.fsel = len(self.project.effects) - 1
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self._update_duration()
        self._load_clip_fields()
        self._load_audio_fields()
        self._load_overlay_fields()
        self._load_fx_fields()

    def _select_clip(self, idx: int) -> None:
        self.sel = idx
        self.asel = -1
        self.osel = -1
        self.fsel = -1
        self._load_fx_fields()
        self._load_clip_fields()
        self._load_audio_fields()
        self._load_overlay_fields()
        c = self.project.clips[idx]
        self._open_media(c.path, int(c.in_pt * 1000), int(c.out_pt * 1000), autoplay=False)

    def move_clip(self, delta: int) -> None:
        i, j = self.sel, self.sel + delta
        cl = self.project.clips
        if 0 <= i < len(cl) and 0 <= j < len(cl):
            cl[i], cl[j] = cl[j], cl[i]
            self._refresh_timeline(select=j)

    def delete_clip(self) -> None:
        if 0 <= self.sel < len(self.project.clips):
            self.project.reattach_audio(self.sel)       # getrennten Ton des Clips mit entfernen
            del self.project.clips[self.sel]
            self._refresh_timeline(select=min(self.sel, len(self.project.clips) - 1))

    def apply_transition_to_all(self) -> None:
        if not (0 <= self.sel < len(self.project.clips)):
            return
        c = self.project.clips[self.sel]
        for other in self.project.clips:
            other.transition, other.transition_dur = c.transition, c.transition_dur
        self._refresh_timeline()
        self.statusBar().showMessage("Übergang auf alle Clips angewendet (der letzte Clip hat keinen).")

    def remove_silence(self) -> list[int]:
        """Öffnet das Fenster „Stille entfernen“ für den gewählten Clip und teilt ihn bei „Anwenden“ in die Stücke dazwischen."""
        if not (0 <= self.sel < len(self.project.clips)):
            self.statusBar().showMessage("Zuerst einen Clip in der Timeline anklicken.")
            return []
        c = self.project.clips[self.sel]
        if c.is_image or not c.has_audio:
            self.statusBar().showMessage("Dieser Clip hat keinen Ton.")
            return []
        dlg = SilenceDialog(c, self)
        self._silence_dialog = dlg
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.cuts:
            return []
        return self.apply_silence_cuts(dlg.cuts)

    def split_scenes(self) -> list[int]:
        """Öffnet das Fenster „An Szenenwechseln teilen“ für den gewählten Clip."""
        if not (0 <= self.sel < len(self.project.clips)):
            self.statusBar().showMessage("Zuerst einen Clip in der Timeline anklicken.")
            return []
        c = self.project.clips[self.sel]
        if c.is_image:
            self.statusBar().showMessage("Bei einem Standbild geht das nicht.")
            return []
        dlg = SceneDialog(c, self)
        self._scene_dialog = dlg
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.cuts:
            return []
        return self.apply_scene_cuts(dlg.cuts)

    def apply_scene_cuts(self, cuts) -> list[int]:
        try:
            used = scenes.apply(self.project, self.sel, cuts)
        except scenes.SceneError as exc:
            QMessageBox.warning(self, "Szenenerkennung", str(exc))
            return []
        self._refresh_timeline(select=used[0])
        self.statusBar().showMessage(f"Der Clip wurde in {len(used)} Szenen geteilt. Rückgängig mit Strg+Z.")
        return used

    def apply_silence_cuts(self, cuts) -> list[int]:
        try:
            used = silence.apply(self.project, self.sel, cuts)
        except silence.SilenceError as exc:
            QMessageBox.warning(self, "Stille entfernen", str(exc))
            return []
        self._refresh_timeline(select=used[0])
        self.statusBar().showMessage(f"Stille entfernt: der Clip besteht jetzt aus {len(used)} Stücken. Rückgängig mit Strg+Z.")
        return used

    def split_clip(self) -> None:
        if not (0 <= self.sel < len(self.project.clips)):
            return
        c = self.project.clips[self.sel]
        t = self.player.position() / 1000.0
        if self._cur_path != c.path or not (c.in_pt + 0.1 < t < c.out_pt - 0.1):
            self.statusBar().showMessage("Zum Teilen: Clip auswählen und im Player an die gewünschte Stelle springen.")
            return
        if c.audio_detached:
            self.project.reattach_audio(self.sel)
            self.statusBar().showMessage("Der getrennte Ton wurde vor dem Teilen wieder mit dem Clip verbunden.")
        second = copy.deepcopy(c)
        second.uid = uuid.uuid4().hex[:10]
        c.out_pt = t
        c.transition = ""            # zwischen den beiden Hälften bleibt der Schnitt hart
        second.in_pt = t
        self.project.clips.insert(self.sel + 1, second)
        self._refresh_timeline(select=self.sel)

    # ------------------------------------------------------- Clip-Eigenschaften
    def _load_clip_fields(self) -> None:
        ok = 0 <= self.sel < len(self.project.clips)
        self.clip_tab.setEnabled(ok)
        if not ok:
            self.clip_name.setText("Kein Clip ausgewählt")
            self._load_grade_fields()
            self._load_motion_fields()
            return
        c = self.project.clips[self.sel]
        self._loading = True
        self.clip_name.setText(c.name)
        self.clip_in.setRange(0.0, c.duration)
        self.clip_out.setRange(0.05, c.duration)
        self.clip_in.setValue(c.in_pt)
        self.clip_in.setEnabled(not c.is_image)
        self.clip_out.setValue(c.out_pt)
        self.clip_speed.setValue(c.speed)
        self.clip_vol.setValue(int(c.volume * 100))
        self.clip_vol_label.setText(f"{int(c.volume * 100)} %")
        self.clip_mute.setChecked(c.mute)
        self.clip_mute.setEnabled(c.has_audio and not c.audio_detached)
        self.clip_vol.setEnabled(not c.audio_detached)
        self.clip_audio_note.setVisible(c.audio_detached)
        self.clip_rev.setChecked(c.reverse)
        self.clip_dn.setValue(int(c.denoise))
        self.clip_vc.setValue(int(c.voice))
        self.clip_dn.setEnabled(c.has_audio and not c.audio_detached)
        self.clip_vc.setEnabled(c.has_audio and not c.audio_detached)
        self.clip_dn_label.setText(self._fix_text(c.denoise))
        self.clip_vc_label.setText(self._fix_text(c.voice))
        self.clip_stab.setValue(int(c.stabilize))
        self.clip_stab.setEnabled(not c.is_image)
        self.clip_stab_label.setText(f"{int(c.stabilize)} %" if c.stabilize else "aus")
        self._on_ramp_text()
        last = self.sel >= len(self.project.clips) - 1
        self.clip_trans.setCurrentIndex(max(0, self.clip_trans.findData(c.transition)))
        self.clip_trans_dur.setValue(c.transition_dur)
        self.clip_trans.setEnabled(not last)
        self.clip_trans_dur.setEnabled(not last)
        self.clip_trans_note.setVisible(last)
        self._loading = False
        self._show_ck(c)
        self._show_ramp_group()
        self._load_grade_fields()
        self._load_motion_fields()

    # -- Chroma-Key auf dem Hauptvideo
    def _selected_clip(self):
        return self.project.clips[self.sel] if 0 <= self.sel < len(self.project.clips) else None

    def _show_ck(self, c) -> None:
        """Zeigt die Key-Einstellungen des Clips (ruft keine Handler auf)."""
        was = self._loading
        self._loading = True
        valid = exporter.chromakey_filters(c) != ""
        col = (c.key_color or "").strip()
        self.ck_on.setChecked(valid)
        self.ck_swatch.setStyleSheet(
            f"background: {('#' + col.lstrip('#')) if valid else 'transparent'}; border: 1px solid #2c313d; border-radius: 3px;")
        self.ck_sim.setValue(c.key_similarity)
        self.ck_blend.setValue(c.key_blend)
        self.ck_spill.setChecked(c.key_spill)
        bg = (c.key_bg or "").strip()
        self.ck_bg_label.setText(f"Hintergrund: {Path(bg).name}" if bg else "Hintergrund: schwarz")
        for w in (self.ck_green, self.ck_blue, self.ck_pick, self.ck_eye, self.ck_sim, self.ck_blend, self.ck_spill,
                  self.ck_bg_btn, self.ck_bg_clear):
            w.setEnabled(True)
        self._loading = was

    def _ck_changed(self, c) -> None:
        self._show_ck(c)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self._update_duration()

    def _set_ck_color(self, color: str) -> None:
        c = self._selected_clip()
        if self._loading or c is None:
            return
        c.key_color = color.lower()
        self._ck_changed(c)

    def _on_ck_toggle(self, on: bool) -> None:
        c = self._selected_clip()
        if self._loading or c is None:
            return
        if not on:
            c.key_color = ""
        elif exporter.chromakey_filters(c) == "":
            c.key_color = "#00ff00"
        self._ck_changed(c)

    def _on_ck_field(self, *_args) -> None:
        c = self._selected_clip()
        if self._loading or c is None:
            return
        c.key_similarity = self.ck_sim.value()
        c.key_blend = self.ck_blend.value()
        c.key_spill = self.ck_spill.isChecked()
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _pick_ck_color(self) -> None:
        c = self._selected_clip()
        if c is None:
            return
        start = QColor(c.key_color) if exporter.chromakey_filters(c) else QColor("#00ff00")
        col = QColorDialog.getColor(start, self, "Schlüsselfarbe wählen")
        if col.isValid():
            self._set_ck_color(col.name())

    def _pick_ck_from_frame(self) -> None:
        """Pipette: Farbe direkt im Bild des Clips anklicken."""
        c = self._selected_clip()
        if c is None:
            return
        try:
            import tempfile
            from ..core import frames
            d = tempfile.mkdtemp(prefix="fate_pick_")
            self._tmp_dirs.append(Path(d))
            png = str(Path(d) / "pick.png")
            t = c.in_pt + (0.0 if c.is_image else min(1.0, max(0.0, c.out_pt - c.in_pt) / 2.0))
            frames.extract_frame(c.path, png, t)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Pipette", f"Das Bild konnte nicht geladen werden:\n{exc}")
            return
        from .pickdialog import PickDialog
        dlg = PickDialog(png, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.color:
            self._set_ck_color(dlg.color)

    def _key_preview_file(self) -> str:
        """Rechnet das Vorschaubild des Chroma-Keys für den gewählten Clip und gibt den Pfad der PNG-Datei zurück."""
        c = self._selected_clip()
        if c is None:
            raise RuntimeError("Kein Clip gewählt.")
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="fate_keyview_"))
        self._tmp_dirs.append(d)
        png = str(d / "key.png")
        keypreview.render(c, png, height=360)
        return png

    def show_key_preview(self) -> bool:
        """Zeigt das Vorschaubild in einem kleinen Fenster."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            png = self._key_preview_file()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Vorschau", f"Die Vorschau konnte nicht erstellt werden:\n{exc}")
            return False
        finally:
            QApplication.restoreOverrideCursor()
        dlg = QDialog(self)
        dlg.setWindowTitle("Chroma-Key – Vorschau")
        lay = QVBoxLayout(dlg)
        label = QLabel()
        label.setPixmap(QPixmap(png))
        lay.addWidget(label)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self._key_preview_dialog = dlg
        dlg.exec()
        return True

    def _pick_ck_bg(self) -> None:
        c = self._selected_clip()
        if c is None:
            return
        f, _ = QFileDialog.getOpenFileName(self, "Hintergrund wählen (Bild oder Video)", "",
                                           "Bilder und Videos (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.mkv *.avi *.webm *.m4v);;Alle Dateien (*)")
        if f:
            c.key_bg = f
            self._ck_changed(c)

    def _clear_ck_bg(self) -> None:
        c = self._selected_clip()
        if c is None or self._loading:
            return
        c.key_bg = ""
        self._ck_changed(c)

    def _on_clip_field(self, *_args) -> None:
        self.clip_vol_label.setText(f"{self.clip_vol.value()} %")
        self.clip_dn_label.setText(self._fix_text(self.clip_dn.value()))
        self.clip_vc_label.setText(self._fix_text(self.clip_vc.value()))
        self.clip_stab_label.setText(f"{self.clip_stab.value()} %" if self.clip_stab.value() else "aus")
        if self._loading or not (0 <= self.sel < len(self.project.clips)):
            return
        c = self.project.clips[self.sel]
        c.in_pt = min(self.clip_in.value(), self.clip_out.value() - 0.05)
        c.out_pt = max(self.clip_out.value(), c.in_pt + 0.05)
        c.speed = self.clip_speed.value()
        c.volume = self.clip_vol.value() / 100.0
        c.mute = self.clip_mute.isChecked()
        if not c.audio_detached:
            c.denoise, c.voice = int(self.clip_dn.value()), int(self.clip_vc.value())
        c.reverse = self.clip_rev.isChecked()
        c.stabilize = 0 if c.is_image else int(self.clip_stab.value())
        c.transition = str(self.clip_trans.currentData() or "")
        c.transition_dur = self.clip_trans_dur.value()
        self.project.sync_linked()
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self._update_duration()

    # -- Geschwindigkeitskurve
    def _fill_ramp_presets(self, select: str = "") -> None:
        """Vorlagenliste: eingebaute Kurven, darunter „Meine Kurven“ (Kennung „my:Name“)."""
        was = self.ramp_preset.blockSignals(True)
        self.ramp_preset.clear()
        self.ramp_preset.addItem("– Vorlage wählen –", "")
        for rid, rname, _rpts in rampmod.PRESETS:
            self.ramp_preset.addItem(rname, rid)
        for c in rampmod.clean_saved(settings.load().get("my_ramps")):
            self.ramp_preset.addItem(f"★ {c['name']}", f"my:{c['name']}")
        self.ramp_preset.setCurrentIndex(max(0, self.ramp_preset.findData(select)) if select else 0)
        self.ramp_preset.blockSignals(was)
        if hasattr(self, "ramp_del"):
            self.ramp_del.setEnabled(str(self.ramp_preset.currentData() or "").startswith("my:"))

    def _on_ramp_preset(self, *_args) -> None:
        rid = self.ramp_preset.currentData()
        self.ramp_del.setEnabled(isinstance(rid, str) and rid.startswith("my:"))
        if isinstance(rid, str) and rid.startswith("my:"):
            for c in rampmod.clean_saved(settings.load().get("my_ramps")):
                if c["name"] == rid[3:]:
                    self.ramp_text.setText(rampmod.format_points(c["points"]))
                    return
        for pid, _name, pts in rampmod.PRESETS:
            if pid == rid:
                self.ramp_text.setText(rampmod.format_points(pts))
                return

    def save_my_ramp(self, name: str | None = None) -> bool:
        """Aktuelle Kurve aus dem Textfeld unter einem Namen speichern. name=None: nach dem Namen fragen."""
        try:
            pts = rampmod.parse_points(self.ramp_text.text())
        except rampmod.SpeedRampError as exc:
            self.ramp_info.setText(str(exc))
            return False
        if name is None:
            name, ok = QInputDialog.getText(self, "Kurve speichern", "Name der Kurve:", text="Meine Kurve")
            if not ok:
                return False
        try:
            saved = rampmod.add_saved(settings.load().get("my_ramps"), name, pts)
        except rampmod.SpeedRampError as exc:
            self.ramp_info.setText(str(exc))
            return False
        settings.save({"my_ramps": saved})
        clean = " ".join(name.split())[:rampmod.MAX_NAME]
        self._fill_ramp_presets(select=f"my:{clean}")
        self.ramp_info.setText(f"Kurve „{clean}“ gespeichert (Vorlagenliste, mit ★).")
        return True

    def delete_my_ramp(self) -> bool:
        rid = self.ramp_preset.currentData()
        if not (isinstance(rid, str) and rid.startswith("my:")):
            return False
        settings.save({"my_ramps": rampmod.remove_saved(settings.load().get("my_ramps"), rid[3:])})
        self._fill_ramp_presets()
        self.ramp_info.setText(f"Kurve „{rid[3:]}“ gelöscht.")
        return True

    def _on_ramp_curve(self, pts) -> None:
        """Zeichenfläche → Textfeld (das Textfeld bleibt die Quelle für „Kurve anwenden“)."""
        self.ramp_text.setText(rampmod.format_points(pts))

    def _on_ramp_text(self, *_args) -> None:
        """Zeigt, wie lang der Clip mit dieser Kurve wird (oder was an der Eingabe nicht stimmt)."""
        text = self.ramp_text.text()
        text = text.strip() if isinstance(text, str) else ""
        if text:                                       # Textfeld/Vorlage → Zeichenfläche
            try:
                self.ramp_curve.set_points(rampmod.parse_points(text))
            except rampmod.SpeedRampError:
                pass
        if not text:
            self.ramp_info.setText("")
            return
        c = self.project.clips[self.sel] if 0 <= self.sel < len(self.project.clips) else None
        try:
            pts = rampmod.parse_points(text)
        except rampmod.SpeedRampError as exc:
            self.ramp_info.setText(str(exc))
            return
        if c is None:
            self.ramp_info.setText("Zuerst einen Clip in der Timeline anklicken.")
            return
        g = rampmod.group_of(self.project, self.sel)
        if g:                                                  # Kurve ersetzen: der ganze ursprüngliche Clip zählt
            first, last = self.project.clips[g[0]], self.project.clips[g[1]]
            cur = sum(k.length for k in self.project.clips[g[0]:g[1] + 1])
            new = rampmod.new_length(pts, max(0.05, last.out_pt - first.in_pt), first.ramp_speed)
        else:
            cur = c.length
            new = rampmod.new_length(pts, max(0.05, c.out_pt - c.in_pt), c.speed)
        self.ramp_info.setText(f"Länge: {fmt_time(cur)} → {fmt_time(new)}")

    def _show_ramp_group(self) -> None:
        """Gehört der gewählte Clip zu einer angewendeten Kurve? Dann ihre Punkte zeigen und den Knopf umbenennen."""
        g = rampmod.group_of(self.project, self.sel)
        if g is None:
            self._ramp_loaded_id = ""
            self.ramp_group_note.setText("")
            self.btn_ramp.setText("Kurve anwenden (teilt den Clip in Abschnitte)")
            self.btn_ramp_off.setEnabled(False)
            return
        first = self.project.clips[g[0]]
        self.ramp_group_note.setText(f"Dieser Clip gehört zu einer Kurve ({g[1] - g[0] + 1} Abschnitte). Ändere die Punkte "
                                     "und klicke „Kurve ersetzen“ – die Abschnitte werden neu berechnet.")
        self.btn_ramp.setText("Kurve ersetzen (berechnet die Abschnitte neu)")
        self.btn_ramp_off.setEnabled(True)
        if self._ramp_loaded_id != first.ramp_id:          # nur beim Wechsel in eine andere Kurve: eigene Eingaben nicht überschreiben
            self._ramp_loaded_id = first.ramp_id
            self.ramp_text.setText(rampmod.format_points(first.ramp_pts))

    def remove_speed_ramp(self) -> bool:
        """Führt die Abschnitte der Kurve wieder zu einem Clip zusammen."""
        try:
            idx = rampmod.merge_group(self.project, self.sel)
        except rampmod.SpeedRampError as exc:
            self.ramp_info.setText(str(exc))
            self.statusBar().showMessage(str(exc))
            return False
        self._refresh_timeline(select=idx)
        self.statusBar().showMessage("Kurve entfernt: der Clip ist wieder in einem Stück. Rückgängig mit Strg+Z.")
        return True

    def apply_speed_ramp(self) -> list[int]:
        """Teilt den gewählten Clip nach der Kurve in Abschnitte mit gleichbleibender Geschwindigkeit."""
        if not (0 <= self.sel < len(self.project.clips)):
            self.statusBar().showMessage("Zuerst einen Clip in der Timeline anklicken.")
            return []
        try:
            pts = rampmod.parse_points(self.ramp_text.text())
            was_detached = self.project.clips[self.sel].audio_detached
            replaced = rampmod.group_of(self.project, self.sel) is not None
            used = rampmod.apply(self.project, self.sel, pts)
        except rampmod.SpeedRampError as exc:
            self.ramp_info.setText(str(exc))
            self.statusBar().showMessage(str(exc))
            return []
        self._refresh_timeline(select=used[0])
        self.statusBar().showMessage(f"Geschwindigkeitskurve {'ersetzt' if replaced else 'angewendet'}: {len(used)} Abschnitte"
                                     + (" (der getrennte Ton wurde wieder mit dem Clip verbunden)" if was_detached else "")
                                     + ". Rückgängig mit Strg+Z.")
        return used

    # ----------------------------------------------- Drehen / Zuschneiden / Bewegung
    def _load_motion_fields(self) -> None:
        ok = 0 <= self.sel < len(self.project.clips)
        self.motion_body.setEnabled(ok)
        if not ok:
            self.motion_name.setText("Zuerst einen Clip in der Timeline anklicken")
            self.kf_list.clear()
            return
        c = self.project.clips[self.sel]
        self._loading = True
        self.motion_name.setText(f"Clip: {c.name}  ({c.rotate % 360}° gedreht)")
        self.tf_flip_h.setChecked(c.flip_h)
        self.tf_flip_v.setChecked(c.flip_v)
        for key, attr in (("l", "crop_l"), ("r", "crop_r"), ("t", "crop_t"), ("b", "crop_b")):
            self.tf_crop[key].setValue(getattr(c, attr))
        self.kf_ease.setChecked(c.motion_ease)
        self.cmb_motion.setCurrentIndex(0)
        self._loading = False
        self._load_kf_list(0 if c.keyframes else -1)

    def _kf_title(self, k: dict) -> str:
        return (f"{k.get('t', 0) * 100:.0f} %   Zoom {k.get('zoom', 100):.0f} %   "
                f"x {k.get('x', 0):.0f}  y {k.get('y', 0):.0f}  ∠ {k.get('rot', 0):.1f}°")

    def _load_kf_list(self, select: int = -1) -> None:
        c = self._selected_clip()
        self._loading = True
        self.kf_list.clear()
        if c is not None:
            for k in c.keyframes:
                self.kf_list.addItem(self._kf_title(k))
        self._loading = False
        if 0 <= select < self.kf_list.count():
            self.kf_list.setCurrentRow(select)
        else:
            self.kf_box.setEnabled(False)

    def _on_kf_selected(self, row: int) -> None:
        c = self._selected_clip()
        if c is None or not (0 <= row < len(c.keyframes)):
            self.kf_box.setEnabled(False)
            return
        k = c.keyframes[row]
        self._loading = True
        self.kf_fields["t"].setValue(float(k.get("t", 0)) * 100.0)
        for key in ("zoom", "x", "y", "rot"):
            self.kf_fields[key].setValue(float(k.get(key, 100.0 if key == "zoom" else 0.0)))
        self._loading = False
        self.kf_box.setEnabled(True)

    def _on_kf_field(self, *_args) -> None:
        c = self._selected_clip()
        if self._loading or c is None:
            return
        c.motion_ease = self.kf_ease.isChecked()
        row = self.kf_list.currentRow()
        if 0 <= row < len(c.keyframes):
            k = c.keyframes[row]
            k["t"] = self.kf_fields["t"].value() / 100.0
            for key in ("zoom", "x", "y", "rot"):
                k[key] = self.kf_fields[key].value()
            item = self.kf_list.item(row)
            if item:
                item.setText(self._kf_title(k))

    def add_keyframe(self) -> None:
        c = self._selected_clip()
        if c is None:
            return
        last = c.keyframes[-1] if c.keyframes else {"zoom": 100.0, "x": 0.0, "y": 0.0, "rot": 0.0}
        t = 0.0 if not c.keyframes else min(1.0, max(k.get("t", 0) for k in c.keyframes) + 0.25)
        if len(c.keyframes) >= 12:
            self.statusBar().showMessage("Mehr als 12 Keyframes pro Clip sind nicht möglich.")
            return
        c.keyframes.append({"t": t, "zoom": last.get("zoom", 100.0), "x": last.get("x", 0.0),
                            "y": last.get("y", 0.0), "rot": last.get("rot", 0.0)})
        self._load_kf_list(len(c.keyframes) - 1)
        self._refresh_timeline_only()

    def remove_keyframe(self) -> None:
        c = self._selected_clip()
        row = self.kf_list.currentRow()
        if c is not None and 0 <= row < len(c.keyframes):
            del c.keyframes[row]
            self._load_kf_list(min(row, len(c.keyframes) - 1))
            self._refresh_timeline_only()

    def clear_motion(self) -> None:
        c = self._selected_clip()
        if c is not None:
            c.keyframes = []
            self._load_kf_list()
            self._refresh_timeline_only()

    def _on_motion_preset(self, _idx: int) -> None:
        c = self._selected_clip()
        pid = self.cmb_motion.currentData()
        if self._loading or c is None or not pid:
            return
        m = presets.get("motions", pid)
        if m:
            c.keyframes = copy.deepcopy(m["keyframes"])
            self._load_kf_list(0)
            self._refresh_timeline_only()
            self.statusBar().showMessage(f"Bewegung „{m['name']}“ gesetzt – sichtbar in der Vorschau mit Effekten.")

    def apply_motion_to_all(self) -> None:
        c = self._selected_clip()
        if c is None:
            return
        for o in self.project.clips:
            o.keyframes = copy.deepcopy(c.keyframes)
            o.motion_ease = c.motion_ease
        self._refresh_timeline_only()
        self.statusBar().showMessage("Bewegung auf alle Clips angewendet.")

    def _rotate_clip(self, delta: int) -> None:
        c = self._selected_clip()
        if c is None:
            return
        c.rotate = (c.rotate + delta) % 360
        self.motion_name.setText(f"Clip: {c.name}  ({c.rotate}° gedreht)")
        self._refresh_timeline_only()

    def _on_transform_field(self, *_args) -> None:
        c = self._selected_clip()
        if self._loading or c is None:
            return
        c.flip_h = self.tf_flip_h.isChecked()
        c.flip_v = self.tf_flip_v.isChecked()
        c.crop_l, c.crop_r = self.tf_crop["l"].value(), self.tf_crop["r"].value()
        c.crop_t, c.crop_b = self.tf_crop["t"].value(), self.tf_crop["b"].value()
        self._refresh_timeline_only()

    def reset_transform(self) -> None:
        c = self._selected_clip()
        if c is None:
            return
        c.rotate, c.flip_h, c.flip_v = 0, False, False
        c.crop_l = c.crop_r = c.crop_t = c.crop_b = 0.0
        self._load_motion_fields()
        self._refresh_timeline_only()

    def _refresh_timeline_only(self) -> None:
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    # --------------------------------------------------------------- Untertitel
    @staticmethod
    def _cue_title(c: SubtitleCue) -> str:
        first = " ".join(c.text.split())
        return f"{fmt_time(c.start)}  {first[:34] + '…' if len(first) > 34 else first}"

    def _refresh_sub_font_combo(self) -> None:
        cur = self.project.sub_style.font
        self.sub_font.blockSignals(True)
        self.sub_font.clear()
        for name, path in self._fonts.items():
            self.sub_font.addItem(name, path)
        self.sub_font.addItem("Standardschrift", "")
        idx = self.sub_font.findData(paths.resolve_font(cur))
        self.sub_font.setCurrentIndex(idx if idx >= 0 else max(0, self.sub_font.count() - 1))
        self.sub_font.blockSignals(False)

    def _load_sub_list(self, select: int = -1) -> None:
        self._loading = True
        self.sub_list.clear()
        for c in self.project.subtitles:
            self.sub_list.addItem(self._cue_title(c))
        self._loading = False
        if 0 <= select < self.sub_list.count():
            self.sub_list.setCurrentRow(select)
        else:
            self.sub_edit_box.setEnabled(False)

    def _load_sub_style(self) -> None:
        st = self.project.sub_style
        self._loading = True
        self._refresh_sub_font_combo()
        self.sub_size.setValue(st.size_pct)
        self.sub_pos.setCurrentIndex(max(0, self.sub_pos.findData(st.position)))
        self.sub_anim.setCurrentIndex(max(0, self.sub_anim.findData(st.anim)))
        self.sub_box.setChecked(st.box)
        self._sub_color = st.color if st.color.startswith("#") else "#ffffff"
        self.btn_sub_color.setStyleSheet(f"background: {self._sub_color}; color: black; font-weight: 600;")
        self.sub_karaoke.setChecked(bool(st.karaoke))
        self.sub_kar_mode.setCurrentIndex(max(0, self.sub_kar_mode.findData(st.karaoke_mode)))
        self._sub_kar_color = st.karaoke_color if str(st.karaoke_color).startswith("#") else karaoke.DEFAULT_COLOR
        self.btn_sub_kar_color.setStyleSheet(f"background: {self._sub_kar_color}; color: black; font-weight: 600;")
        self.sub_kar_mode.setEnabled(bool(st.karaoke))
        self.btn_sub_kar_color.setEnabled(bool(st.karaoke))
        self._loading = False

    def _on_sub_selected(self, row: int) -> None:
        if not (0 <= row < len(self.project.subtitles)):
            self.sub_edit_box.setEnabled(False)
            return
        c = self.project.subtitles[row]
        self._loading = True
        self.sub_text.setPlainText(c.text)
        self.sub_from.setValue(c.start)
        self.sub_to.setValue(c.end)
        self._loading = False
        self.sub_edit_box.setEnabled(True)

    def _on_sub_field(self, *_args) -> None:
        row = self.sub_list.currentRow()
        if self._loading or not (0 <= row < len(self.project.subtitles)):
            return
        c = self.project.subtitles[row]
        c.text = self.sub_text.toPlainText()
        c.start = self.sub_from.value()
        c.end = max(self.sub_to.value(), c.start + 0.1)
        item = self.sub_list.item(row)
        if item:
            item.setText(self._cue_title(c))

    def _on_sub_style(self, *_args) -> None:
        if self._loading:
            return
        st = self.project.sub_style
        st.font = self.sub_font.currentData() or ""
        st.size_pct = self.sub_size.value()
        st.position = self.sub_pos.currentData() or "bottom"
        st.anim = self.sub_anim.currentData() or "none"
        st.box = self.sub_box.isChecked()
        st.color = self._sub_color
        st.karaoke = self.sub_karaoke.isChecked()
        st.karaoke_mode = self.sub_kar_mode.currentData() or "stay"
        st.karaoke_color = self._sub_kar_color
        self.sub_kar_mode.setEnabled(st.karaoke)
        self.btn_sub_kar_color.setEnabled(st.karaoke)

    def pick_sub_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._sub_color), self, "Untertitel-Farbe")
        if c.isValid():
            self._sub_color = c.name()
            self.btn_sub_color.setStyleSheet(f"background: {self._sub_color}; color: black; font-weight: 600;")
            self._on_sub_style()

    def pick_sub_kar_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._sub_kar_color), self, "Karaoke-Hervorhebungsfarbe")
        if c.isValid():
            self._sub_kar_color = c.name()
            self.btn_sub_kar_color.setStyleSheet(f"background: {self._sub_kar_color}; color: black; font-weight: 600;")
            self._on_sub_style()

    def _sub_preview_file(self) -> str:
        t = subpreview.pick_time(self.project, self.timeline.playhead, self.sub_list.currentRow())
        if t is None:
            raise RuntimeError("Es gibt noch keinen Untertitel-Eintrag.")
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="fate_subview_"))
        self._tmp_dirs.append(d)
        png = str(d / "sub.png")
        subpreview.render(self.project, t, png, height=480)
        return png

    def show_sub_preview(self) -> bool:
        """Zeigt das Untertitel-Vorschaubild in einem kleinen Fenster."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            png = self._sub_preview_file()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Vorschau", f"Die Vorschau konnte nicht erstellt werden:\n{exc}")
            return False
        finally:
            QApplication.restoreOverrideCursor()
        dlg = QDialog(self)
        dlg.setWindowTitle("Untertitel – Vorschau")
        lay = QVBoxLayout(dlg)
        label = QLabel()
        label.setPixmap(QPixmap(png))
        lay.addWidget(label)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self._sub_preview_dialog = dlg
        dlg.exec()
        return True

    def add_subtitle(self) -> None:
        t0 = self.timeline.playhead if self.timeline.playhead >= 0 else 0.0
        self.project.subtitles.append(SubtitleCue(t0, t0 + 2.0, "Neuer Untertitel"))
        self.project.subtitles.sort(key=lambda c: c.start)
        idx = next(i for i, c in enumerate(self.project.subtitles) if c.text == "Neuer Untertitel" and c.start == t0)
        self._load_sub_list(idx)

    def remove_subtitle(self) -> None:
        row = self.sub_list.currentRow()
        if 0 <= row < len(self.project.subtitles):
            del self.project.subtitles[row]
            self._load_sub_list(min(row, len(self.project.subtitles) - 1))

    def clear_subtitles(self) -> None:
        self.project.subtitles.clear()
        self._load_sub_list()

    def import_srt(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "SRT-Datei importieren", "", SRT_FILTER)
        if f:
            self.load_srt(f)

    def load_srt(self, path: str) -> int:
        try:
            cues = subs.read_srt(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Untertitel", f"Datei konnte nicht gelesen werden:\n{exc}")
            return 0
        self.project.subtitles = cues
        self._load_sub_list(0 if cues else -1)
        self.statusBar().showMessage(f"{len(cues)} Untertitel importiert.")
        return len(cues)

    def export_srt(self) -> None:
        if not self.project.subtitles:
            self.statusBar().showMessage("Es gibt noch keine Untertitel.")
            return
        f, _ = QFileDialog.getSaveFileName(self, "SRT speichern", "Untertitel.srt", SRT_FILTER)
        if f:
            subs.write_srt(f, self.project.subtitles)
            self.statusBar().showMessage(f"Gespeichert: {f}")

    def auto_subtitles(self) -> None:
        if not self.project.clips:
            QMessageBox.information(self, APP_NAME, "Füge zuerst Clips zur Timeline hinzu.")
            return
        if self._asr_worker is not None:
            return
        if subs.find_whisper() is None:
            self.setup_whisper(then_run=True)
            return
        self.btn_asr.setEnabled(False)
        self.btn_asr.setText("Erkenne Sprache … (kann dauern)")
        w = AsrWorker(self.project.to_json(), self.sub_lang.currentData() or "auto", self)
        w.done.connect(self._on_asr_done)
        self._asr_worker = w
        w.start()

    def _on_asr_done(self, cues, err: str) -> None:
        self._asr_worker = None
        then, self._asr_then = self._asr_then, None
        self.btn_asr.setEnabled(True)
        self.btn_asr.setText("Untertitel automatisch erzeugen")
        if err or cues is None:
            QMessageBox.warning(self, "Untertitel", err or "Es wurde nichts erkannt.")
            return
        self.project.subtitles = subs.split_long(cues)
        self._load_sub_list(0 if self.project.subtitles else -1)
        self.statusBar().showMessage(f"{len(self.project.subtitles)} Untertitel erkannt – bitte kurz prüfen und korrigieren.")
        if then is not None:
            then()                                  # der Export, der auf die Untertitel gewartet hat

    # ----------------------------------------------------------- Bild-in-Bild
    def _selected_overlay(self):
        if 0 <= self.osel < len(self.project.overlays):
            return self.project.overlays[self.osel]
        return None

    def _load_overlay_fields(self) -> None:
        o = self._selected_overlay()
        self.ov_group.setEnabled(o is not None)
        if o is None:
            self.ov_name.setText("Keins gewählt – in der Timeline anklicken")
            return
        self._loading = True
        self.ov_name.setText(o.name + ("  (Standbild)" if o.is_image else ""))
        self.ov_in.setRange(0.0, o.duration)
        self.ov_out.setRange(0.05, o.duration)
        self.ov_start.setValue(o.start)
        self.ov_in.setValue(o.in_pt)
        self.ov_in.setEnabled(not o.is_image)
        self.ov_out.setValue(o.out_pt)
        self.ov_speed.setValue(o.speed)
        self.ov_x.setValue(o.x_pct)
        self.ov_y.setValue(o.y_pct)
        self.ov_size.setValue(o.size_pct)
        self.ov_opacity.setValue(o.opacity)
        self.ov_rot.setValue(o.rot)
        self.ov_fin.setValue(o.fade_in)
        self.ov_fout.setValue(o.fade_out)
        self.ov_border.setChecked(o.border)
        self.ov_reverse.setChecked(bool(o.reverse) and not o.is_image)
        self.ov_reverse.setEnabled(not o.is_image)
        self.ov_sound.setChecked(bool(o.sound) and not o.is_image)
        self.ov_sound.setEnabled(not o.is_image)
        self.ov_volume.setValue(o.volume)
        self.ov_volume.setEnabled(not o.is_image and bool(o.sound))
        in_split = splitlib.is_split(o)
        self.ov_split_note.setVisible(in_split)
        for wdg in (self.ov_x, self.ov_y, self.ov_size, self.ov_border, self.ov_corner, self.ov_rot):
            wdg.setEnabled(not in_split)
        self.ov_cz.setValue(o.cell_zoom)
        self.ov_cdx.setValue(o.cell_dx)
        self.ov_cdy.setValue(o.cell_dy)
        for wdg in (self.ov_cz, self.ov_cdx, self.ov_cdy):
            wdg.setEnabled(in_split)
        self._show_key(o)
        self._show_ovk(o)
        key = next((k for k, (cx, cy) in OVERLAY_CORNERS.items() if abs(cx - o.x_pct) < 0.5 and abs(cy - o.y_pct) < 0.5), "")
        self.ov_corner.setCurrentIndex(max(0, self.ov_corner.findData(key)))
        self._loading = False

    def _on_overlay_corner(self, *_args) -> None:
        o = self._selected_overlay()
        key = self.ov_corner.currentData()
        if self._loading or o is None or key not in OVERLAY_CORNERS:
            return
        o.x_pct, o.y_pct = OVERLAY_CORNERS[key]
        self._load_overlay_fields()
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _on_overlay_field(self, *_args) -> None:
        o = self._selected_overlay()
        if self._loading or o is None:
            return
        o.start = self.ov_start.value()
        o.in_pt = min(self.ov_in.value(), self.ov_out.value() - 0.05)
        o.out_pt = max(self.ov_out.value(), o.in_pt + 0.05)
        o.speed = self.ov_speed.value()
        o.x_pct = self.ov_x.value()
        o.y_pct = self.ov_y.value()
        o.size_pct = self.ov_size.value()
        o.opacity = self.ov_opacity.value()
        o.rot = self.ov_rot.value()
        o.fade_in = self.ov_fin.value()
        o.fade_out = self.ov_fout.value()
        o.border = self.ov_border.isChecked()
        o.cell_zoom, o.cell_dx, o.cell_dy = self.ov_cz.value(), self.ov_cdx.value(), self.ov_cdy.value()
        o.reverse = bool(self.ov_reverse.isChecked()) and not o.is_image
        o.sound = bool(self.ov_sound.isChecked()) and not o.is_image
        o.volume = self.ov_volume.value()
        self.ov_volume.setEnabled(not o.is_image and o.sound)
        o.key_similarity = self.ov_key_sim.value()
        o.key_blend = self.ov_key_blend.value()
        o.key_spill = self.ov_key_spill.isChecked()
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _show_key(self, o) -> None:
        """Zeigt die Chroma-Key-Einstellungen des Overlays (ruft keine Handler auf)."""
        was = self._loading
        self._loading = True
        col = (o.key_color or "").strip()
        valid = exporter.chromakey_filters(o) != ""
        self.ov_key_on.setChecked(valid)
        self.ov_key_swatch.setStyleSheet(
            f"background: {('#' + col.lstrip('#')) if valid else 'transparent'}; border: 1px solid #2c313d; border-radius: 3px;")
        self.ov_key_sim.setValue(o.key_similarity)
        self.ov_key_blend.setValue(o.key_blend)
        self.ov_key_spill.setChecked(o.key_spill)
        for w in (self.ov_key_green, self.ov_key_blue, self.ov_key_pick, self.ov_key_sim, self.ov_key_blend,
                  self.ov_key_spill, self.ov_key_full):
            w.setEnabled(True)
        self._loading = was

    def _set_key_color(self, color: str) -> None:
        o = self._selected_overlay()
        if self._loading or o is None:
            return
        o.key_color = color.lower()
        self._show_key(o)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _on_key_toggle(self, on: bool) -> None:
        o = self._selected_overlay()
        if self._loading or o is None:
            return
        if not on:
            o.key_color = ""
        elif exporter.chromakey_filters(o) == "":          # noch keine (oder ungültige) Farbe → Grün
            o.key_color = "#00ff00"
        self._show_key(o)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _pick_key_color(self) -> None:
        o = self._selected_overlay()
        if o is None:
            return
        start = QColor(o.key_color) if exporter.chromakey_filters(o) else QColor("#00ff00")
        col = QColorDialog.getColor(start, self, "Schlüsselfarbe wählen")
        if col.isValid():
            self._set_key_color(col.name())

    def _overlay_source_frame(self, o: OverlayClip) -> str:
        """Standbild aus dem Bild-in-Bild-Video (nahe am Anfang des benutzten Teils) für die Pipette; Pfad der PNG-Datei."""
        import tempfile
        from ..core import frames
        d = tempfile.mkdtemp(prefix="fate_pick_")
        self._tmp_dirs.append(Path(d))
        png = str(Path(d) / "pick.png")
        t = o.in_pt + (0.0 if o.is_image else min(1.0, max(0.0, o.out_pt - o.in_pt) / 2.0))
        frames.extract_frame(o.path, png, t)
        return png

    def _pick_key_from_frame(self) -> None:
        """Pipette: Farbe direkt im Bild des Videos anklicken."""
        o = self._selected_overlay()
        if o is None:
            return
        try:
            png = self._overlay_source_frame(o)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Pipette", f"Das Bild konnte nicht geladen werden:\n{exc}")
            return
        from .pickdialog import PickDialog
        dlg = PickDialog(png, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.color:
            self._set_key_color(dlg.color)

    def _overlay_fullscreen(self) -> None:
        o = self._selected_overlay()
        if o is None:
            return
        o.x_pct, o.y_pct, o.size_pct = 50.0, 50.0, 100.0
        self._load_overlay_fields()
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _select_overlay(self, idx: int) -> None:
        self.osel = idx
        self.asel = -1
        self.fsel = -1
        self._load_fx_fields()
        self._load_audio_fields()
        self._load_overlay_fields()
        self.tabs.setCurrentIndex(OVERLAY_TAB)

    def _on_overlay_edited(self, idx: int) -> None:
        if idx == self.osel:
            self._load_overlay_fields()

    def add_overlay_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Bild-in-Bild hinzufügen", "", VIDEO_FILTER)
        if files:
            self.add_overlay_files(files)

    def add_overlay_files(self, files: list[str]) -> None:
        errors = []
        t0 = self.timeline.playhead if self.timeline.playhead >= 0 else 0.0
        for f in files:
            try:
                info = probe(f)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{Path(f).name}: {exc}")
                continue
            if info.is_image:
                o = OverlayClip(f, IMAGE_MAX, 0.0, info.duration, start=t0, is_image=True, size_pct=25.0)
            else:
                o = OverlayClip(f, info.duration, 0.0, info.duration, start=t0)
            self.project.overlays.append(o)
            self.osel = len(self.project.overlays) - 1
            self.asel = -1
        if errors:
            QMessageBox.warning(self, "Bild-in-Bild", "Nicht alle Dateien konnten gelesen werden:\n\n" + "\n".join(errors))
        self._refresh_timeline()
        if self._selected_overlay() is not None:
            self.tabs.setCurrentIndex(OVERLAY_TAB)

    def remove_overlay(self) -> None:
        if self._selected_overlay() is None:
            self.statusBar().showMessage("Zuerst ein Bild-in-Bild in der Timeline anklicken.")
            return
        del self.project.overlays[self.osel]
        self.osel = -1
        self._refresh_timeline()

    # ------------------------------------------------------------------ Ton
    def _selected_audio(self):
        if 0 <= self.asel < len(self.project.audio_clips):
            return self.project.audio_clips[self.asel]
        return None

    def _load_audio_fields(self) -> None:
        a = self._selected_audio()
        self.aud_group.setEnabled(a is not None)
        if a is None:
            self.aud_name.setText("Kein Audioblock gewählt – in der Timeline anklicken")
            return
        self._loading = True
        self.aud_name.setText(a.name)
        self.aud_track.setCurrentIndex(max(0, self.aud_track.findData(a.track)))
        self.aud_in.setRange(0.0, a.duration)
        self.aud_out.setRange(0.05, a.duration)
        self.aud_start.setValue(a.start)
        self.aud_in.setValue(a.in_pt)
        self.aud_out.setValue(a.out_pt)
        self.aud_speed.setValue(a.speed)
        self.aud_vol.setValue(int(round(a.volume * 100)))
        self.aud_vol_label.setText(f"{int(round(a.volume * 100))} %")
        self.aud_dn.setValue(int(a.denoise))
        self.aud_vc.setValue(int(a.voice))
        self.aud_dn_label.setText(self._fix_text(a.denoise))
        self.aud_vc_label.setText(self._fix_text(a.voice))
        self.aud_fin.setValue(a.fade_in)
        self.aud_fout.setValue(a.fade_out)
        self.aud_loop.setChecked(a.loop)
        self.aud_mute.setChecked(a.mute)
        self.aud_rev.setChecked(a.reverse)
        self.btn_aud_reattach.setEnabled(a.kind == "video")
        self._loading = False

    def _on_audio_field(self, *_args) -> None:
        self.aud_vol_label.setText(f"{self.aud_vol.value()} %")
        self.aud_dn_label.setText(self._fix_text(self.aud_dn.value()))
        self.aud_vc_label.setText(self._fix_text(self.aud_vc.value()))
        a = self._selected_audio()
        if self._loading or a is None:
            return
        a.track = int(self.aud_track.currentData() or 2)
        a.start = self.aud_start.value()
        a.in_pt = min(self.aud_in.value(), self.aud_out.value() - 0.05)
        a.out_pt = max(self.aud_out.value(), a.in_pt + 0.05)
        a.speed = self.aud_speed.value()
        a.volume = self.aud_vol.value() / 100.0
        a.denoise, a.voice = int(self.aud_dn.value()), int(self.aud_vc.value())
        a.fade_in = self.aud_fin.value()
        a.fade_out = self.aud_fout.value()
        a.loop = self.aud_loop.isChecked()
        a.mute = self.aud_mute.isChecked()
        a.reverse = self.aud_rev.isChecked()
        if a.kind == "video":
            i = self.project.clip_index(a.link)
            if i >= 0:
                a.link_offset = a.start - self.project.clip_start(i)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _select_audio(self, idx: int) -> None:
        self.asel = idx
        self.osel = -1
        self.fsel = -1
        self._load_fx_fields()
        self._load_overlay_fields()
        self._load_audio_fields()
        self.tabs.setCurrentIndex(AUDIO_TAB)

    def _on_audio_edited(self, idx: int) -> None:
        """Der Block wurde mit der Maus verschoben oder gekürzt."""
        if idx == self.asel:
            self._load_audio_fields()
            a = self._selected_audio()
            if a is not None:
                self.statusBar().showMessage(f"{a.name}: Start {fmt_time(a.start)}, Länge {fmt_time(a.length)}")

    def _load_mix_fields(self) -> None:
        p = self.project
        self._loading = True
        for t in (1, 2, 3):
            vol = float(p.track_volume.get(str(t), 1.0))
            self._mix_sliders[t].setValue(int(round(vol * 100)))
            self._mix_labels[t].setText(f"{int(round(vol * 100))} %")
            self._mix_mutes[t].setChecked(bool(p.track_mute.get(str(t), False)))
        self.mix_duck.setChecked(p.ducking)
        self.mix_duck_amount.setValue(int(round(p.ducking_amount * 100)))
        self.mix_duck_label.setText(f"{int(round(p.ducking_amount * 100))} %")
        self.mix_norm.setChecked(p.normalize)
        self.mix_lufs.setCurrentIndex(max(0, self.mix_lufs.findData(float(p.lufs_target))))
        self.mix_lufs.setEnabled(p.normalize)
        self.mix_duck_amount.setEnabled(p.ducking)
        self._loading = False

    def _on_mix_field(self, *_args) -> None:
        for t in (1, 2, 3):
            self._mix_labels[t].setText(f"{self._mix_sliders[t].value()} %")
        self.mix_duck_label.setText(f"{self.mix_duck_amount.value()} %")
        self.mix_duck_amount.setEnabled(self.mix_duck.isChecked())
        self.mix_lufs.setEnabled(self.mix_norm.isChecked())
        if self._loading:
            return
        p = self.project
        for t in (1, 2, 3):
            p.track_volume[str(t)] = self._mix_sliders[t].value() / 100.0
            p.track_mute[str(t)] = self._mix_mutes[t].isChecked()
        p.ducking = self.mix_duck.isChecked()
        p.ducking_amount = self.mix_duck_amount.value() / 100.0
        p.normalize = self.mix_norm.isChecked()
        tv = self.mix_lufs.currentData()
        p.lufs_target = float(tv) if isinstance(tv, (int, float)) else -14.0
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def add_audio_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Musik / Audio hinzufügen", "", AUDIO_FILTER)
        if files:
            self.add_audio_files(files, track=2)

    def add_audio_files(self, files: list[str], track: int = 2) -> None:
        errors = []
        for f in files:
            try:
                dur = probe_audio(f)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{Path(f).name}: {exc}")
                continue
            self.project.audio_clips.append(AudioClip(f, dur, start=0.0, track=track))
            self.asel = len(self.project.audio_clips) - 1
        if errors:
            QMessageBox.warning(self, "Audio", "Nicht alle Dateien konnten gelesen werden:\n\n" + "\n".join(errors))
        self._refresh_timeline()
        self._request_waveforms()
        if self._selected_audio() is not None:
            self.tabs.setCurrentIndex(AUDIO_TAB)

    def detach_selected_audio(self) -> None:
        if not (0 <= self.sel < len(self.project.clips)):
            self.statusBar().showMessage("Zuerst einen Videoclip in der Timeline anklicken.")
            return
        a = self.project.detach_audio(self.sel)
        if a is None:
            self.statusBar().showMessage("Dieser Clip hat keinen Ton oder der Ton ist schon getrennt.")
            return
        self.asel = len(self.project.audio_clips) - 1
        self._refresh_timeline()
        self._request_waveforms()
        self.tabs.setCurrentIndex(AUDIO_TAB)
        self.statusBar().showMessage("Ton getrennt: liegt jetzt auf A1 und lässt sich einzeln bearbeiten.")

    def reattach_selected_clip(self) -> None:
        if not (0 <= self.sel < len(self.project.clips)):
            return
        c = self.project.clips[self.sel]
        if not c.audio_detached:
            self.statusBar().showMessage("Der Ton dieses Clips ist nicht getrennt.")
            return
        self.project.reattach_audio(self.sel)
        self.asel = -1
        self._refresh_timeline()
        self.statusBar().showMessage("Ton wieder mit dem Clip verbunden.")

    def reattach_selected_audio(self) -> None:
        a = self._selected_audio()
        if a is None or a.kind != "video":
            return
        i = self.project.clip_index(a.link)
        if i >= 0:
            self.project.reattach_audio(i)
        else:
            self.project.audio_clips.remove(a)
        self.asel = -1
        self._refresh_timeline()
        self.statusBar().showMessage("Ton wieder mit dem Clip verbunden.")

    def remove_audio(self) -> None:
        a = self._selected_audio()
        if a is None:
            self.statusBar().showMessage("Zuerst einen Audioblock in der Timeline anklicken.")
            return
        del self.project.audio_clips[self.asel]
        # Ein getrennter Clip-Ton bleibt dann bewusst stumm (über „Ton wieder verbinden“ zurückholbar).
        self.asel = -1
        self._refresh_timeline()

    # ------------------------------------------------------------------ Mehrfachauswahl
    def _on_multi_changed(self) -> None:
        n = len(self.timeline.multi_items())
        if n:
            self.statusBar().showMessage(f"{n} Blöcke gewählt – Entf löscht sie, Strg+D dupliziert sie, Ziehen verschiebt Bild-in-Bild, "
                                         "Audio und Effekte gemeinsam. Esc hebt die Auswahl auf.")

    def _on_multi_edited(self) -> None:
        self._refresh_timeline_only()

    def delete_multi(self) -> int:
        items = self.timeline.multi_items()
        n = sellib.delete(self.project, items)
        self.timeline.clear_multi()
        self.asel = self.osel = self.fsel = -1
        self._load_audio_fields()
        self._load_overlay_fields()
        self._load_fx_fields()
        self._refresh_timeline(select=min(self.sel, len(self.project.clips) - 1))
        self.statusBar().showMessage(f"{n} Blöcke gelöscht. Rückgängig mit Strg+Z.")
        return n

    def duplicate_multi(self) -> int:
        items = self.timeline.multi_items()
        new = sellib.duplicate_items(self.project, items)
        self._refresh_timeline()
        self.timeline.set_multi(new)
        self.statusBar().showMessage(f"{len(new)} Blöcke dupliziert – die Kopien liegen direkt hinter den Originalen.")
        return len(new)

    def delete_selected(self) -> None:
        if self.timeline.multi_items():
            self.delete_multi()
        elif self.fsel >= 0:
            self.remove_effect_block()
        elif self.osel >= 0:
            self.remove_overlay()
        elif self.asel >= 0:
            self.remove_audio()
        else:
            self.delete_clip()

    def ripple_delete_selected(self) -> int:
        """Strg+Entf: gewählte Clips löschen und alles dahinter (auch Bild-in-Bild, Ton, Effekte) nachrücken lassen.
        Andere gewählte Blöcke (Bild-in-Bild, Audio, Effekt) werden einfach gelöscht."""
        items = self.timeline.multi_items()
        if not items:
            if self.fsel >= 0:
                items = [("f", self.fsel)]
            elif self.osel >= 0:
                items = [("o", self.osel)]
            elif self.asel >= 0:
                items = [("a", self.asel)]
            elif 0 <= self.sel < len(self.project.clips):
                items = [("v", self.sel)]
        if not items:
            return 0
        clips = [i for k, i in items if k == "v"]
        other = [(k, i) for k, i in items if k != "v"]
        n = sellib.delete(self.project, other) if other else 0
        r = gapslib.ripple_delete(self.project, clips, self.act_ripple_tracks.isChecked()) if clips else None
        self.timeline.clear_multi()
        self.asel = self.osel = self.fsel = -1
        self._load_audio_fields()
        self._load_overlay_fields()
        self._load_fx_fields()
        self._refresh_timeline(select=max(0, min(self.sel, len(self.project.clips) - 1)))
        if r:
            n += r["clips"] + r["removed"]
            self.statusBar().showMessage(f"{r['clips']} Clip(s) gelöscht, {r['seconds']:.1f} s Lücke geschlossen. Rückgängig mit Strg+Z.")
        else:
            self.statusBar().showMessage(f"{n} Block/Blöcke gelöscht. Rückgängig mit Strg+Z.")
        return n

    def insert_freeze(self, seconds: float | None = None) -> bool:
        """Hält das Bild unter dem Abspielkopf für einige Sekunden an: der Clip wird geteilt und ein Standbild-Clip eingefügt."""
        if not self.project.clips:
            self.statusBar().showMessage("Zuerst ein Video in die Timeline legen.")
            return False
        t = max(0.0, self.timeline.playhead)
        loc = freezelib.locate(self.project, t)
        if loc is None:
            self.statusBar().showMessage("Hier liegt schon ein Standbild – bitte den Abspielkopf auf ein Video setzen.")
            return False
        idx, local = loc
        if seconds is None:
            seconds, ok = QInputDialog.getDouble(self, "Standbild einfügen", "Wie lange soll das Bild stehen bleiben (Sekunden)?",
                                                 freezelib.DEFAULT_SECONDS, freezelib.MIN_SECONDS, freezelib.MAX_SECONDS, 1)
            if not ok:
                return False
        c = self.project.clips[idx]
        png = freezelib.new_png_path()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            freezelib.extract(c, local, png)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Standbild einfügen", f"Das Bild konnte nicht aus dem Video geholt werden:\n{exc}")
            return False
        QApplication.restoreOverrideCursor()
        n = freezelib.insert(self.project, idx, local, png, seconds)
        self._refresh_timeline(select=n)
        self.statusBar().showMessage(f"Standbild eingefügt ({freezelib.clamp_seconds(seconds):.1f} s). Rückgängig mit Strg+Z.")
        return True

    def close_all_gaps(self) -> int:
        """Menü: leere Stellen zwischen Blöcken auf den Zusatzspuren (Bild-in-Bild, Ton, Effekte) entfernen."""
        r = gapslib.close_all(self.project)
        if not r["gaps"]:
            self.statusBar().showMessage("Keine Lücken auf den Zusatzspuren gefunden.")
            return 0
        self._refresh_timeline_only()
        self.statusBar().showMessage(f"{r['gaps']} Lücke(n) geschlossen, {r['moved']} Block/Blöcke verschoben. Rückgängig mit Strg+Z.")
        return r["gaps"]

    # ------------------------------------------------------------------ Marker
    def add_marker(self) -> None:
        """Taste M: Marker am Abspielkopf; liegt dort schon einer, wird er gelöscht (zweimal M = wieder weg)."""
        t = max(0.0, self.timeline.playhead)
        i = markerlib.nearest(self.project, t, 0.05)
        if i >= 0:
            markerlib.remove(self.project, i)
            self.statusBar().showMessage("Marker entfernt.")
        else:
            markerlib.add(self.project, t)
            self.statusBar().showMessage(f"Marker bei {fmt_time(t)} gesetzt. Strg+← / Strg+→ springen von Marker zu Marker, M am selben Punkt entfernt ihn.")
        self._refresh_timeline_only()

    def goto_marker(self, direction: int) -> None:
        t = markerlib.step(self.project, max(0.0, self.timeline.playhead), direction)
        if t is None:
            self.statusBar().showMessage("Kein weiterer Marker in dieser Richtung.")
            return
        self._seek_project(min(t, max(0.0, self.project.duration - 0.01)))

    def rename_marker(self) -> None:
        i = markerlib.nearest(self.project, max(0.0, self.timeline.playhead), 0.25)
        if i < 0:
            self.statusBar().showMessage("Zum Benennen den Abspielkopf auf einen Marker stellen.")
            return
        name, ok = QInputDialog.getText(self, "Marker benennen", "Name:", text=self.project.markers[i].get("name", ""))
        if ok:
            markerlib.rename(self.project, i, name.strip())
            self._refresh_timeline_only()

    def build_chapters_dialog(self) -> QDialog:
        """Fenster mit der Kapitelliste für die YouTube-Beschreibung (aus benannten Markern), Hinweisen und Kopieren-Knopf."""
        dlg = QDialog(self)
        dlg.setWindowTitle("YouTube-Kapitel")
        dlg.resize(520, 460)
        lay = QVBoxLayout(dlg)
        intro = QLabel("Benannte Marker werden zu Kapiteln. Marker setzen mit M, benennen über Bearbeiten → Marker → Marker benennen.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Name des ersten Kapitels (0:00), falls dort kein Marker liegt:"))
        ed = QLineEdit("Anfang")
        row.addWidget(ed)
        lay.addLayout(row)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        lay.addWidget(box, 1)
        info = QLabel()
        info.setWordWrap(True)
        lay.addWidget(info)
        btns = QHBoxLayout()
        b_copy = QPushButton("Liste kopieren")
        b_close = QPushButton("Schließen")
        btns.addStretch(1)
        btns.addWidget(b_copy)
        btns.addWidget(b_close)
        lay.addLayout(btns)

        def refresh():
            r = chapterlib.build(self.project, ed.text())
            box.setPlainText(r["text"])
            msg = [f"<span style='color:#d33'>• {x}</span>" for x in r["problems"]] + [f"• {x}" for x in r["notes"]]
            if r["ok"]:
                msg.insert(0, "<span style='color:#2a2'>Die Liste erfüllt die YouTube-Regeln.</span>")
            info.setText("<br>".join(msg))
            dlg._result = r

        def copy():
            QApplication.clipboard().setText(box.toPlainText())
            self.statusBar().showMessage("Kapitelliste kopiert – in die YouTube-Beschreibung einfügen.")

        ed.textChanged.connect(refresh)
        b_copy.clicked.connect(copy)
        b_close.clicked.connect(dlg.accept)
        dlg._edit, dlg._box, dlg._info, dlg._copy, dlg._refresh = ed, box, info, copy, refresh
        refresh()
        return dlg

    def show_chapters(self) -> None:
        if not self.project.clips:
            self.statusBar().showMessage("Zuerst ein Video in die Timeline legen.")
            return
        self._chapters_dialog = self.build_chapters_dialog()
        self._chapters_dialog.exec()

    def clear_markers(self) -> None:
        n = markerlib.clear(self.project)
        self.statusBar().showMessage(f"{n} Marker entfernt. Rückgängig mit Strg+Z." if n else "Es gibt keine Marker.")
        self._refresh_timeline_only()

    def duplicate_selected(self) -> None:
        """Strg+D: legt eine Kopie des gewählten Blocks direkt dahinter (gleiche Reihenfolge wie beim Löschen)."""
        try:
            if self.timeline.multi_items():
                self.duplicate_multi()
            elif self.fsel >= 0:
                self.fsel, fits = duplicate.effect(self.project, self.fsel)
                self.asel = self.osel = -1
                self._load_audio_fields()
                self._load_overlay_fields()
                self._load_fx_fields()
                self._refresh_timeline_only()
                self.statusBar().showMessage("Effekt-Block dupliziert." if fits else
                                             "Effekt-Block dupliziert – er reichte bis zum Ende, die Kopie liegt darüber.")
            elif self.osel >= 0:
                self.osel = duplicate.overlay(self.project, self.osel)
                self._refresh_timeline()
                self.statusBar().showMessage("Bild-in-Bild dupliziert – die Kopie liegt direkt dahinter.")
            elif self.asel >= 0:
                self.asel = duplicate.audio(self.project, self.asel)
                self._refresh_timeline()
                self.statusBar().showMessage("Audioblock dupliziert – die Kopie liegt direkt dahinter.")
            else:
                new = duplicate.clip(self.project, self.sel)
                self._refresh_timeline(select=new)
                self.statusBar().showMessage("Clip dupliziert – die Kopie liegt direkt dahinter. Rückgängig mit Strg+Z.")
        except duplicate.DuplicateError as e:
            self.statusBar().showMessage(str(e))

    def _request_waveforms(self) -> None:
        self._wave_workers = [w for w in self._wave_workers if w.isRunning()]
        for a in self.project.audio_clips:
            if a.path in self._waves or a.path in self._wave_pending or not os.path.exists(a.path):
                continue
            self._wave_pending.add(a.path)
            w = WaveformWorker(a.path)
            w.done.connect(self._on_wave_done)
            self._wave_workers.append(w)
            w.start()

    def _on_wave_done(self, path: str, png: str, err: str) -> None:
        self._wave_pending.discard(path)
        if png:
            pm = QPixmap(png)
            if not pm.isNull():
                self._waves[path] = pm
                self.timeline.set_waveforms(self._waves)

    # ------------------------------------------------- Rückgängig / Sicherung
    def _is_dirty(self) -> bool:
        return self.project.to_json() != self._saved_state

    def _hist_tick(self) -> None:
        state = self.project.to_json()
        self._history.observe(state, time.monotonic())
        if state != self._live_last_state:
            self._live_last_state = state
            self._live_changed()
        name = Path(self._project_file).name if self._project_file else "Neues Projekt"
        self.setWindowTitle(f"{name}{' *' if state != self._saved_state else ''} – {APP_NAME} {VERSION}")
        self.act_undo.setEnabled(self._history.can_undo())
        self.act_redo.setEnabled(self._history.can_redo())
        self._sync_zoom_slider()

    def _apply_state(self, state: str) -> None:
        self.project = Project.from_json(state)
        self.asel = -1
        self.osel = -1
        self._sync_controls_from_project()
        self._refresh_timeline(select=min(self.sel, len(self.project.clips) - 1))
        self._request_waveforms()
        self._history.rebase(self.project.to_json())

    def undo(self) -> None:
        state = self._history.undo(self.project.to_json())
        if state is None:
            self.statusBar().showMessage("Nichts zum Rückgängigmachen.")
            return
        self._apply_state(state)
        self.statusBar().showMessage("Rückgängig gemacht.")

    def redo(self) -> None:
        state = self._history.redo()
        if state is None:
            self.statusBar().showMessage("Nichts zum Wiederholen.")
            return
        self._apply_state(state)
        self.statusBar().showMessage("Wiederholt.")

    def _autosave_path(self) -> Path:
        return paths.user_dir() / "autosave.cforge"

    def autosave_now(self) -> bool:
        if not (self.project.clips or self.project.audio_clips or self.project.overlays or self.project.subtitles) or not self._is_dirty():
            return False
        try:
            self.project.save(str(self._autosave_path()))
            return True
        except OSError:
            return False

    def _remove_autosave(self) -> None:
        try:
            self._autosave_path().unlink()
        except OSError:
            pass

    def _offer_restore(self) -> None:
        f = self._autosave_path()
        if not f.exists() or f.stat().st_size == 0:
            return
        r = QMessageBox.question(self, APP_NAME, "Das Programm wurde beim letzten Mal nicht normal beendet.\n"
                                 "Die automatisch gesicherte Arbeit wiederherstellen?")
        if r == QMessageBox.StandardButton.Yes:
            self.restore_autosave()
        else:
            self._remove_autosave()

    def restore_autosave(self) -> bool:
        f = self._autosave_path()
        try:
            proj = Project.load(str(f))
        except Exception:  # noqa: BLE001
            return False
        self.project = proj
        self._project_file = ""
        self.asel = -1
        self.osel = -1
        self._sync_controls_from_project()
        self._refresh_timeline(select=0 if proj.clips else -1)
        self._request_waveforms()
        self._history.reset(self.project.to_json())
        self._saved_state = Project().to_json()     # gilt als „nicht gespeichert“
        self._remove_autosave()
        if proj.missing_paths():
            self.relink_dialog()
        return True

    def relink_dialog(self) -> None:
        missing = self.project.missing_paths()
        if not missing:
            self.statusBar().showMessage("Alle Dateien sind vorhanden.")
            return
        names = "\n".join(Path(m).name for m in missing[:12]) + ("\n…" if len(missing) > 12 else "")
        r = QMessageBox.question(self, "Fehlende Dateien", f"Diese Dateien wurden nicht gefunden:\n\n{names}\n\n"
                                 "Einen Ordner wählen, in dem sie liegen (Unterordner werden mitgesucht)?")
        if r != QMessageBox.StandardButton.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, "Ordner mit den fehlenden Dateien")
        if folder:
            self.relink_missing(folder)

    def relink_missing(self, folder: str) -> int:
        found, still = self.project.relink(folder)
        self._refresh_timeline()
        self._request_waveforms()
        msg = f"{found} Datei(en) wiedergefunden."
        if still:
            msg += f" Noch fehlend: {', '.join(Path(m).name for m in still[:5])}"
        self.statusBar().showMessage(msg)
        return found

    # ---------------------------------------------- Timeline: Maus & Abspielkopf
    def _on_clip_edited(self, idx: int) -> None:
        self.project.sync_linked()
        if idx == self.sel:
            self._load_clip_fields()
        self._update_duration()
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _reorder_clip(self, src: int, dst: int) -> None:
        cl = self.project.clips
        if 0 <= src < len(cl) and 0 <= dst < len(cl) and src != dst:
            self.timeline.clear_multi()
            cl.insert(dst, cl.pop(src))
            self._refresh_timeline(select=dst)

    def _seek_project(self, t: float) -> None:
        if self.view_stack.currentIndex() == 1:
            self._mask_edit_off()
        cl = self.project.clips
        if not cl:
            return
        idx = len(cl) - 1
        for i in range(len(cl)):
            if t < self.project.clip_start(i) + cl[i].length:
                idx = i
                break
        c = cl[idx]
        local = max(0.0, min(c.length, t - self.project.clip_start(idx)))
        if idx != self.sel or self.asel >= 0 or self.osel >= 0 or self.fsel >= 0:
            self.sel = idx
            self.asel = -1
            self.osel = -1
            self.fsel = -1
            self._load_fx_fields()
            self._load_overlay_fields()
            self._load_clip_fields()
            self._load_audio_fields()
        src_ms = int((c.in_pt + local * c.speed) * 1000)
        if self._live_valid_for(t):
            self.player.setPosition(int((t - self._live_start_t) * 1000))      # bleibt in der Vorschau mit Effekten
            self.player.pause()
        else:
            self._open_media(c.path, src_ms, int(c.out_pt * 1000), autoplay=False)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self._show_time(t)

    # --------------------------------------------------------------- Player
    def _open_media(self, path: str, seek_ms: int, limit_ms: int | None, autoplay: bool, live: bool = True) -> None:
        if is_image_path(path):          # Bilder zeigt der Player nicht – die Live-Vorschau rechnet sie
            self.player.stop()
            self._cur_path = ""
            if self._live_on:
                self._live_timer.start(450)
            else:
                self.statusBar().showMessage("Standbild – die Vorschau zeigt es über „Vorschau mit Effekten“.")
            return
        if path != self._preview_path:
            self._preview_path = ""
        self._limit_ms = limit_ms
        self._autoplay = autoplay
        self._pending_seek = seek_ms
        if path != self._cur_path:
            self._cur_path = path
            self.player.setSource(QUrl.fromLocalFile(path))
        else:
            self._apply_pending()
        if live and self._live_on and path != self._live_path:
            self._live_timer.start(450)          # Original läuft → Vorschau mit Effekten nachliefern

    def _apply_pending(self) -> None:
        if self._pending_seek is None:
            return
        self.player.setPosition(self._pending_seek)
        self._pending_seek = None
        if self._autoplay:
            self.player.play()
        else:
            self.player.pause()

    def _on_media_status(self, status) -> None:
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._apply_pending()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._live_end_of_media()

    def _on_position(self, pos: int) -> None:
        if self._preview_path and self._cur_path == self._preview_path:
            self._show_time(self._preview_start + pos / 1000.0)
        elif 0 <= self.sel < len(self.project.clips):
            c = self.project.clips[self.sel]
            if c.path == self._cur_path:
                rel = (pos / 1000.0 - c.in_pt) / max(c.speed, 0.01)
                if -0.05 <= rel <= c.length + 0.05:
                    self._show_time(self.project.clip_start(self.sel) + max(0.0, rel))
        if self._limit_ms is not None and pos >= self._limit_ms:
            self.player.pause()
        self._live_on_position(pos)

    def toggle_play(self) -> None:
        if self.view_stack.currentIndex() == 1:
            self._mask_edit_off()
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self._live_playing = False
            return
        if self._limit_ms is not None and self.player.position() >= self._limit_ms - 50 and 0 <= self.sel < len(self.project.clips):
            self.player.setPosition(int(self.project.clips[self.sel].in_pt * 1000))
        self.player.play()
        if self._live_on and not (self._live_path and self._cur_path == self._live_path):
            self._live_timer.start(150)

    # ---------------------------------------------------------- Export/Vorschau
    def _run_job(self, cmd, total, title: str, on_done, measure: str = "") -> None:
        dlg = QProgressDialog(title, "Abbrechen", 0, 100, self)
        dlg.setWindowTitle(APP_NAME)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        worker = ExportWorker(cmd, total, self, measure_path=measure)
        self._job_t0 = time.monotonic()

        def on_progress(p: float):
            dlg.setValue(int(p * 100))
            eta = exporter.format_eta(time.monotonic() - self._job_t0, p)
            dlg.setLabelText(f"{title}  {eta}" if eta else title)

        worker.progress.connect(on_progress)
        dlg.canceled.connect(worker.cancel)

        diagnostics.log("%s gestartet (%.1f s Länge)", title, total)

        def finished(err: str):
            dlg.close()
            self._worker = None
            self._last_loudness = worker.loudness if not err else None
            if err:
                diagnostics.log_error("%s fehlgeschlagen: %s", title, err[-1500:])
            else:
                diagnostics.log("%s fertig nach %.1f s", title, time.monotonic() - self._job_t0)
            on_done(err)

        worker.done.connect(finished)
        self._worker = worker
        worker.start()

    def _check_ready(self) -> bool:
        if not self.project.clips:
            QMessageBox.information(self, APP_NAME, "Füge zuerst mindestens einen Clip zur Timeline hinzu.")
            return False
        if self._worker is not None:
            QMessageBox.information(self, APP_NAME, "Es läuft bereits ein Export.")
            return False
        gone = [a.name for a in self.project.audio_clips + self.project.overlays if not os.path.exists(a.path)]
        if gone:
            QMessageBox.warning(self, APP_NAME, "Diese Audiodateien fehlen:\n" + "\n".join(gone))
            return False
        return True

    def export_video(self) -> None:
        if not self._check_ready():
            return
        if self._stab_wait(self.export_video):
            self.statusBar().showMessage("Stabilisierung wird zuerst analysiert – der Export startet danach.")
            return
        if not self._confirm_chars():
            return
        out, _ = QFileDialog.getSaveFileName(self, "Video exportieren", str(Path.home() / "Mein_Video.mp4"), "MP4-Video (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        use_hw = self.chk_hw.isChecked() and exporter.hw_encoder() is not None
        if not self._subs_before_export(lambda: self._start_export(out, use_hw)):
            return
        self._start_export(out, use_hw)

    def _subs_before_export(self, proceed) -> bool:
        """True = der Export darf sofort starten. Fehlen die Untertitel für die SRT-Datei, wird gefragt, ob sie automatisch erzeugt
        werden sollen; dann läuft die Erkennung zuerst und `proceed` startet den Export danach (Rückgabe False)."""
        if not self.project.sub_srt or self.project.subtitles:
            return True
        if subs.find_whisper() is None:
            QMessageBox.information(self, "Untertitel-Datei", "Es gibt noch keine Untertitel, und die Spracherkennung ist nicht eingerichtet "
                                    "(Hilfe → Spracherkennung einrichten). Der Export läuft ohne Untertitel-Datei.")
            return True
        if self._asr_worker is not None:
            return True
        ans = QMessageBox.question(self, "Untertitel-Datei", "Es gibt noch keine Untertitel. Jetzt mit der Spracherkennung erzeugen?\n\n"
                                   "Das kann etwas dauern. Danach startet der Export. „Nein“ exportiert ohne Untertitel-Datei.")
        if ans != QMessageBox.StandardButton.Yes:
            return True
        self._asr_then = proceed
        self.auto_subtitles()
        if self._asr_worker is None:                # die Erkennung ist gar nicht gestartet: nichts merken, Export läuft normal
            self._asr_then = None
            return True
        return False

    def _write_export_srt(self, video: str) -> str:
        """Legt bei gesetztem Häkchen die SRT neben das Video; gibt einen Satz für die Meldung zurück (leer ohne Häkchen)."""
        if not self.project.sub_srt:
            return ""
        try:
            path = subs.write_export_srt(self.project, video)
        except OSError as exc:
            return f"Die Untertitel-Datei konnte nicht gespeichert werden: {exc}"
        return f"Untertitel-Datei: {Path(path).name}" if path else "Keine Untertitel vorhanden – es wurde keine .srt-Datei gespeichert."

    # -- Beat-Sync (1.5.0)
    def detect_beats(self) -> bool:
        """Öffnet „Beats erkennen“ für den gewählten Audioblock; bei „Anwenden“ gibt es Marker und/oder Schnitte auf den Beat."""
        a = self._selected_audio()
        if a is None:
            self.statusBar().showMessage("Zuerst einen Audioblock (Musik) in der Timeline anklicken.")
            return False
        dlg = BeatDialog(a, self)
        self._beat_dialog = dlg
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.times:
            return False
        return self.apply_beats(dlg.times, dlg.want_markers, dlg.want_cut)

    def apply_beats(self, times: list[float], set_markers: bool, cut: bool) -> bool:
        parts = []
        if cut:
            try:
                changed, skipped = beatlib.snap_clips(self.project, times)
            except beatlib.BeatError as exc:
                QMessageBox.warning(self, "Beats", str(exc))
                return False
            parts.append(f"{changed} Clip(s) auf den Beat gelegt" + (f", {skipped} unverändert (Tempokurve oder zu kurze Quelle)" if skipped else ""))
        if set_markers:
            n = markerlib.add_many(self.project, times)
            parts.append(f"{n} Marker gesetzt")
        self._refresh_timeline()
        self.statusBar().showMessage("Beat-Sync: " + "; ".join(parts) + ". Rückgängig mit Strg+Z.")
        return True

    # -- Standbild (1.5.0)
    def save_still(self) -> None:
        if not self._check_ready():
            return
        t = self.timeline.playhead if self.timeline.playhead >= 0 else 0.0
        out, _ = QFileDialog.getSaveFileName(self, "Bild speichern", str(Path.home() / stillframe.default_name(self.project, t)),
                                             "PNG-Bild (*.png)")
        if out:
            self.run_still(t, out if out.lower().endswith(".png") else out + ".png")

    def run_still(self, t: float, out: str) -> bool:
        """Rechnet das Bild an der Stelle t so wie der Export und speichert es als PNG; False, wenn nichts gestartet wurde."""
        try:
            cmd, total, tmp, png_cmd = stillframe.build(self.project, t, out)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Bild speichern", str(exc))
            return False
        self._tmp_dirs.append(tmp)

        def done(err: str):
            if not err:
                r = subprocess.run(png_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if r.returncode != 0 or not os.path.exists(out):
                    err = r.stderr[-400:] or "Das Bild konnte nicht gespeichert werden."
            if err:
                QMessageBox.critical(self, "Bild speichern fehlgeschlagen", err)
                return
            self.statusBar().showMessage(f"Bild gespeichert: {out}")

        self._run_job(cmd, total, "Bild wird berechnet …", done)
        return True

    # -- GIF (1.5.0)
    def export_gif(self) -> None:
        if not self._check_ready():
            return
        if self._stab_wait(self.export_gif):
            self.statusBar().showMessage("Stabilisierung wird zuerst analysiert – der Export startet danach.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Als animiertes GIF exportieren")
        lay = QVBoxLayout(dlg)
        form = QFormLayout()
        cmb_w, cmb_f = QComboBox(), QComboBox()
        for w in giflib.WIDTHS:
            cmb_w.addItem(f"{w} Pixel breit", w)
        for f in giflib.FPS_CHOICES:
            cmb_f.addItem(f"{f} Bilder pro Sekunde", f)
        cmb_w.setCurrentIndex(max(0, cmb_w.findData(giflib.DEFAULT_WIDTH)))
        cmb_f.setCurrentIndex(max(0, cmb_f.findData(giflib.DEFAULT_FPS)))
        info = QLabel()
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {MUTED};")

        def refresh(*_a):
            info.setText(giflib.describe(self.project, int(cmb_w.currentData()), int(cmb_f.currentData())))

        cmb_w.currentIndexChanged.connect(refresh)
        cmb_f.currentIndexChanged.connect(refresh)
        refresh()
        form.addRow("Größe", cmb_w)
        form.addRow("Flüssigkeit", cmb_f)
        lay.addLayout(form)
        lay.addWidget(info)
        hint = QLabel("Ein GIF hat keinen Ton und nur 256 Farben. Kurze Ausschnitte (bis 30 s) mit wenig Bewegung werden klein.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        out, _ = QFileDialog.getSaveFileName(self, "GIF speichern", str(Path.home() / "Mein_GIF.gif"), "GIF-Bild (*.gif)")
        if out:
            self.run_gif_export(giflib.default_name(out), int(cmb_w.currentData()), int(cmb_f.currentData()))

    def run_gif_export(self, out: str, width: int, fps: int) -> bool:
        """Rechnet das Projekt klein als Zwischenvideo und macht daraus das GIF; False, wenn nichts gestartet wurde."""
        w, h = giflib.size_for(self.project, width)
        secs, _cut = giflib.length_for(self.project)
        try:
            cmd, total, tmp = exporter.build_command(self.project, str(Path(tempfile.mkdtemp(prefix="fate_gif_")) / "mid.mp4"),
                                                      draft=True, preview_height=h, max_seconds=secs)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "GIF-Export", str(exc))
            return False
        self._tmp_dirs.append(tmp)
        mid = cmd[-1]

        def step2(err: str):
            if err:
                QMessageBox.critical(self, "GIF-Export fehlgeschlagen", err)
                return
            gcmd = giflib.gif_command(mid, out, width, fps)

            def finished(err2: str):
                if err2:
                    QMessageBox.critical(self, "GIF-Export fehlgeschlagen", err2)
                    return
                size = os.path.getsize(out) / 1_000_000 if os.path.exists(out) else 0.0
                self.statusBar().showMessage(f"GIF fertig: {out} ({size:.1f} MB)")
                if QMessageBox.question(self, "GIF fertig", f"Gespeichert unter:\n{out}\n\n({size:.1f} MB)\n\nOrdner öffnen?") \
                        == QMessageBox.StandardButton.Yes:
                    self._open_folder(str(Path(out).parent))

            QTimer.singleShot(50, lambda: self._run_job(gcmd, total, "GIF wird geschrieben …", finished))

        self._run_job(cmd, total, "GIF wird vorbereitet …", step2)
        return True

    def _confirm_chars(self) -> bool:
        problems = [(t, missing_chars(t.font, t.text)) for t in self.project.texts]
        problems = [(t, m) for t, m in problems if m]
        if problems:
            detail = "\n".join(f"„{self._text_title(t)}“: {' '.join(m)}" for t, m in problems)
            if QMessageBox.question(self, "Fehlende Zeichen in der Schrift",
                                    "Diese Zeichen gibt es in der gewählten Schrift nicht und sie bleiben im Video leer:\n\n"
                                    f"{detail}\n\nTrotzdem exportieren?") != QMessageBox.StandardButton.Yes:
                return False
        return True

    # -- Mehrere Formate in einem Rutsch (1.4.3)
    def export_multi(self) -> None:
        if not self._check_ready():
            return
        if self._stab_wait(self.export_multi):
            self.statusBar().showMessage("Stabilisierung wird zuerst analysiert – der Export startet danach.")
            return
        if not self._confirm_chars():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Mehrere Formate exportieren")
        lay = QVBoxLayout(dlg)
        info = QLabel("Für jedes angehakte Format entsteht eine eigene Datei. Shorts, TikTok und Reels haben dieselbe Größe – "
                      "meist reicht eine davon. Vorhandene Dateien werden nicht überschrieben (es wird durchnummeriert).")
        info.setWordWrap(True)
        lay.addWidget(info)
        boxes: list[tuple[QCheckBox, str]] = []
        for f in presets.load("formats"):
            cb = QCheckBox(f"{f['name']}  ({f['width']}×{f['height']})")
            cb.setChecked(f["id"] in ("youtube_16_9", "shorts"))
            lay.addWidget(cb)
            boxes.append((cb, f["id"]))
        form = QFormLayout()
        name = QLineEdit("Mein_Video")
        folder = QLineEdit(str(Path.home() / "Videos" if (Path.home() / "Videos").is_dir() else Path.home()))
        pick = QPushButton("Ordner wählen …")
        pick.clicked.connect(lambda *_: folder.setText(QFileDialog.getExistingDirectory(dlg, "Zielordner", folder.text()) or folder.text()))
        form.addRow("Dateiname", name)
        form.addRow("Ordner", folder)
        form.addRow(pick)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ids, fol, base = [fid for cb, fid in boxes if cb.isChecked()], folder.text().strip(), name.text()
        if not self._subs_before_export(lambda: self.run_multi_export(ids, fol, base)):
            return
        self.run_multi_export(ids, fol, base)

    def run_multi_export(self, format_ids: list[str], folder: str, base: str) -> bool:
        """Exportiert nacheinander in jedem gewählten Format; gibt False zurück, wenn gar nichts gestartet wurde."""
        try:
            jobs = multiexport.plan(self.project, format_ids, folder, base)
        except multiexport.MultiExportError as exc:
            QMessageBox.warning(self, "Mehrere Formate exportieren", str(exc))
            return False
        self._multi_jobs, self._multi_ok, self._multi_total = list(jobs), [], len(jobs)
        self._multi_loud = []
        use_hw = self.chk_hw.isChecked() and exporter.hw_encoder() is not None
        self._multi_next(use_hw)
        return True

    def _multi_next(self, use_hw: bool) -> None:
        if not self._multi_jobs:
            done = self._multi_ok
            self.statusBar().showMessage(f"{len(done)} Dateien exportiert.")
            loud = next((t for t in self._multi_loud if t), "")         # der Ton ist in allen Formaten derselbe
            srt_msg = self._write_export_srt(done[0]) if done else ""    # eine Datei genügt: die Zeiten sind in allen Formaten gleich
            if done and QMessageBox.question(self, "Export fertig", f"{len(done)} Dateien gespeichert:\n\n"
                                             + "\n".join(Path(o).name for o in done) + "\n\n" + (loud + "\n\n" if loud else "")
                                             + (srt_msg + "\n\n" if srt_msg else "")
                                             + "Ordner öffnen?") == QMessageBox.StandardButton.Yes:
                self._open_folder(str(Path(done[0]).parent))
            return
        job = self._multi_jobs[0]
        try:
            cmd, total, tmp = exporter.build_command(job.project, job.out, use_hw=use_hw)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export", f"{job.label}: {exc}")
            self._multi_jobs = []
            return
        self._tmp_dirs.append(tmp)
        k = self._multi_total - len(self._multi_jobs) + 1

        def done(err: str):
            if err and use_hw:
                self.statusBar().showMessage("Grafikkarten-Export fehlgeschlagen – neuer Versuch mit dem Prozessor …")
                QTimer.singleShot(200, lambda: self._multi_next(False))
                return
            if err:
                QMessageBox.critical(self, "Export fehlgeschlagen", f"{job.label}:\n{err}\n\nFertig waren {len(self._multi_ok)} von {self._multi_total}.")
                self._multi_jobs = []
                return
            self._multi_ok.append(job.out)
            self._multi_loud.append(self._loudness_text(job.project))
            self._multi_jobs.pop(0)
            self._multi_next(use_hw)

        self._run_job(cmd, total, f"Export {k}/{self._multi_total}: {job.label} …", done, measure=job.out)

    def _loudness_text(self, project=None) -> str:
        """„Lautheit: −13,2 LUFS (Ziel −14,0)“ für den zuletzt fertigen Export (leer, wenn nicht gemessen)."""
        p = project or self.project
        goal = audiomix.lufs_goal(p) if getattr(p, "normalize", False) else None
        return loudcheck.describe(getattr(self, "_last_loudness", None), goal)

    def _start_export(self, out: str, use_hw: bool) -> None:
        try:
            cmd, total, tmp = exporter.build_command(self.project, out, use_hw=use_hw)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export", str(exc))
            return
        self._tmp_dirs.append(tmp)

        def done(err: str):
            if err and use_hw:               # Grafikkarte macht Probleme -> mit dem Prozessor noch einmal
                self.statusBar().showMessage("Grafikkarten-Export fehlgeschlagen – neuer Versuch mit dem Prozessor …")
                QTimer.singleShot(200, lambda: self._start_export(out, False))
                return
            if err:
                QMessageBox.critical(self, "Export fehlgeschlagen", err)
            else:
                loud = self._loudness_text()
                srt_msg = self._write_export_srt(out)
                self.statusBar().showMessage(f"Export fertig: {out}" + (" (mit Grafikkarte)" if use_hw else "") + (f" – {loud}" if loud else "")
                                             + (f" – {srt_msg}" if srt_msg else ""))
                if QMessageBox.question(self, "Export fertig", f"Gespeichert unter:\n{out}\n\n" + (loud + "\n\n" if loud else "")
                                        + (srt_msg + "\n\n" if srt_msg else "")
                                        + "Ordner öffnen?") == QMessageBox.StandardButton.Yes:
                    self._open_folder(str(Path(out).parent))

        self._run_job(cmd, total, "Video wird exportiert …", done, measure=out)

    def _on_perf_changed(self, *_args) -> None:
        settings.save({"preview_len": float(self.cmb_prev_len.currentData() or 0.0),
                       "preview_height": int(self.cmb_prev_q.currentData() or 360),
                       "hw_encode": bool(self.chk_hw.isChecked())})

    def render_preview(self) -> None:
        if not self._check_ready():
            return
        if self._stab_wait(self.render_preview):
            return
        start = max(0.0, self.timeline.playhead)
        if start >= self.project.duration - 0.5:
            start = 0.0
        length = float(self.cmb_prev_len.currentData() or 0.0)
        height = int(self.cmb_prev_q.currentData() or 360)
        target = prevcache.path_for(self.project, start, length, height)

        def play(path: Path):
            self._cur_path = ""
            self._open_media(str(path), 0, None, autoplay=True, live=False)
            self._preview_path, self._preview_start = str(path), start      # nach _open_media setzen
            self.statusBar().showMessage(f"Vorschau ab {fmt_time(start)} (Auflösung {height}p)")

        if target.exists() and target.stat().st_size > 0:
            play(target)
            return
        part = target.with_name(target.stem + ".part.mp4")
        try:
            cmd, total, tmp = exporter.build_command(self.project, str(part), draft=True, start=start,
                                                     max_seconds=length or None, preview_height=height)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Vorschau", str(exc))
            return
        self._tmp_dirs.append(tmp)

        def done(err: str):
            if err:
                QMessageBox.critical(self, "Vorschau fehlgeschlagen", err)
                return
            try:
                os.replace(part, target)
                play(target)
            except OSError:
                play(part)

        self._run_job(cmd, total, "Vorschau wird berechnet …", done)

    # ------------------------------------------------------- Live-Vorschau
    def _live_height(self) -> int:
        return min(360, int(self.cmb_prev_q.currentData() or 360))

    def _set_live_label(self, text: str) -> None:
        self.live_label.setText(text)

    def set_live(self, on: bool) -> None:
        self._live_on = bool(on)
        settings.save({"live_preview": self._live_on})
        if self._live_on:
            self._live_timer.start(100)
        else:
            self._live_timer.stop()
            self._live_pending = None
            if self._live_worker is not None:
                self._live_worker.cancel()
            self._set_live_label("")

    def _live_changed(self) -> None:
        """Das Projekt wurde verändert: kurz warten (weitere Änderungen abwarten), dann neu rechnen."""
        self._live_next_ready = None
        if self._live_on and self.project.clips:
            self._live_timer.start(350)

    def _live_fire(self) -> None:
        self._live_request()

    # -- Stabilisierung: Analyse im Hintergrund
    def _stab_wait(self, then=None) -> bool:
        """True, wenn zuerst analysiert werden muss (`then` läuft danach; ohne `then` wird die Live-Vorschau neu geplant)."""
        if self._stab_worker is not None:
            self._stab_then.append(then)
            return True
        if self._stab_fail_state == self.project.to_json() or not stabilize.missing(self.project):
            return False
        w = StabilizeWorker(copy.deepcopy(self.project), self)
        self._stab_worker = w
        self._stab_then = [then]
        self._set_live_label("⟳ Stabilisierung wird analysiert … 0 %")
        w.progress.connect(lambda p: self._set_live_label(f"⟳ Stabilisierung wird analysiert … {int(p * 100)} %"))
        w.done.connect(self._stab_done)
        w.start()
        return True

    def _stab_done(self, err: str) -> None:
        self._stab_worker = None
        thens, self._stab_then = self._stab_then, []
        self._set_live_label("")
        if err:
            diagnostics.log_error("Stabilisierung fehlgeschlagen: %s", err[-600:])
            self._stab_fail_state = self.project.to_json()
            self.statusBar().showMessage(f"Stabilisierung nicht möglich, es wird die einfache Variante genutzt: {err[-120:]}")
        for t in thens:
            if t is not None:
                t()
        if not any(t is not None for t in thens):
            self._live_changed()

    def _live_valid_for(self, t: float) -> bool:
        """Liegt die Zeit t in der Live-Vorschau, die im Player liegt und zum aktuellen Projekt passt?"""
        return bool(self._live_path and self._cur_path == self._live_path
                    and self._live_start_t - 0.02 <= t <= self._live_start_t + self._live_len - 0.4
                    and self._live_state == self.project.to_json())

    def _live_request(self, start: float | None = None, show: bool = True, at: float | None = None,
                      autoplay: bool | None = None) -> None:
        """Rechnet (bzw. holt aus dem Zwischenspeicher) die Live-Vorschau ab `start` (Standard: Abspielkopf)."""
        if not self._live_on or not self.project.clips:
            return
        if self._worker is not None:                        # Export oder große Vorschau läuft → später
            self._live_timer.start(1500)
            return
        if self._stab_wait(None):                           # Stabilisierung erst analysieren
            return
        if self._live_worker is not None:
            if show:                                        # neuere Anfrage ersetzt die laufende
                self._live_pending = (start, show, at, autoplay)
                self._live_worker.cancel()
            return
        total = self.project.duration
        t = max(0.0, self.timeline.playhead if start is None else start)
        if t >= total - 0.2:
            t = max(0.0, total - 2.0)
        t = round(t, 1)
        height, length = self._live_height(), self._live_len_cfg
        state = self.project.to_json()
        target = prevcache.path_for(self.project, t, length, height)
        ln = max(0.5, min(length, total - t))
        if target.exists() and target.stat().st_size > 0:
            self._live_ready(target, t, ln, state, show, at, autoplay)
            return
        part = target.with_name(target.stem + ".part.mp4")
        try:
            wp, delta, wl = projwin.project_window(self.project, t, length)
            cmd, tot, tmp = exporter.build_command(wp, str(part), draft=True, preview_height=height,
                                                   start=delta, max_seconds=wl)
        except Exception as exc:  # noqa: BLE001
            diagnostics.log_error("Live-Vorschau nicht möglich: %s", exc)
            self._set_live_label("Vorschau nicht möglich")
            self.statusBar().showMessage(f"Live-Vorschau nicht möglich: {str(exc)[:160]}")
            return
        worker = ExportWorker(cmd, tot, self)
        self._live_worker = worker
        if show:
            self._set_live_label("⟳ wird aktualisiert …")

        def finished(err: str) -> None:
            self._live_worker = None
            shutil.rmtree(tmp, ignore_errors=True)
            pend, self._live_pending = self._live_pending, None
            if err:
                try:
                    part.unlink()
                except OSError:
                    pass
                if "Abgebrochen" not in err:
                    diagnostics.log_error("Live-Vorschau fehlgeschlagen: %s", err[-800:])
                    self._set_live_label("Vorschau fehlgeschlagen")
            else:
                final = target
                try:
                    os.replace(part, target)
                except OSError:
                    final = part
                if pend is None:
                    if state != self.project.to_json():       # inzwischen wieder geändert → neu
                        self._live_timer.start(50)
                    else:
                        self._live_ready(final, t, ln, state, show, at, autoplay)
            if pend is not None:
                self._live_request(*pend)
            prevcache.cleanup(max_files=24)

        worker.done.connect(finished)
        worker.start()

    def _live_ready(self, path: Path, t: float, ln: float, state: str, show: bool, at: float | None,
                    autoplay: bool | None) -> None:
        if not show:
            self._live_next_ready = (t, path, state, ln)
            return
        self._live_show(path, t, ln, state, at, autoplay)

    def _live_show(self, path: Path, start: float, ln: float, state: str, at: float | None = None,
                   autoplay: bool | None = None) -> None:
        """Lädt die fertige Live-Vorschau in den Player, an der Stelle, an der der Abspielkopf gerade steht."""
        pos = self.timeline.playhead if at is None else at
        if not (start - 0.06 <= pos <= start + ln + 0.06):
            return                                          # Abspielkopf ist weitergezogen; neue Anfrage kommt von dort
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        play = playing if autoplay is None else autoplay
        self._live_path, self._live_state = str(path), state
        self._live_start_t, self._live_len = start, ln
        self._open_media(str(path), max(0, int(round((pos - start) * 1000))), None, autoplay=play, live=False)
        self._preview_path, self._preview_start = str(path), start      # nach _open_media setzen
        self._live_playing = play
        self._set_live_label("● Live")

    def _live_on_position(self, pos_ms: int) -> None:
        """Beim Abspielen den nächsten Abschnitt schon vorab rechnen, damit es ohne Pause weitergeht."""
        if not (self._live_on and self._live_path and self._cur_path == self._live_path):
            return
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        self._live_playing = True
        nxt = self._live_start_t + self._live_len
        if (pos_ms > 0.45 * self._live_len * 1000 and nxt < self.project.duration - 0.05
                and self._live_worker is None and self._live_next_ready is None):
            self._live_request(start=nxt, show=False)

    def _live_end_of_media(self) -> None:
        """Die Live-Vorschau ist zu Ende: beim Abspielen nahtlos mit dem nächsten Abschnitt weitermachen."""
        if not (self._live_on and self._live_path and self._cur_path == self._live_path and self._live_playing):
            return
        nxt = self._live_start_t + self._live_len
        if nxt >= self.project.duration - 0.05:
            self._live_playing = False
            return
        ready = self._live_next_ready
        if ready and abs(ready[0] - nxt) < 0.11 and ready[2] == self.project.to_json():
            self._live_next_ready = None
            self._live_show(ready[1], ready[0], ready[3], ready[2], at=ready[0], autoplay=True)
        else:
            self._live_request(start=nxt, show=True, at=nxt, autoplay=True)

    @staticmethod
    def _open_folder(folder: str) -> None:
        try:
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
        except OSError:
            pass

    def open_presets_folder(self) -> None:
        self._open_folder(str(paths.user_presets_dir()))
        self.statusBar().showMessage(f"Eigene Presets (JSON) kommen hierhin: {paths.user_presets_dir()}")

    # -------------------------------------------------------------- Projekt
    def collect_project(self) -> None:
        """Datei → Projekt sammeln: fragt Ordner oder ZIP und kopiert alle benutzten Dateien dorthin."""
        info = collectlib.summary(self.project)
        if not info["files"] and not info["missing"]:
            self.statusBar().showMessage("Das Projekt benutzt noch keine Dateien.")
            return
        text = f"{len(info['files'])} Datei(en), {info['bytes'] / 1e6:.0f} MB werden kopiert."
        if info["missing"]:
            text += f"\n{len(info['missing'])} Datei(en) fehlen und werden übersprungen."
        box = QMessageBox(self)
        box.setWindowTitle("Projekt sammeln")
        box.setText(text + "\n\nWohin soll das Projekt mit allen Dateien?")
        b_dir = box.addButton("In einen Ordner", QMessageBox.ButtonRole.AcceptRole)
        b_zip = box.addButton("In eine ZIP-Datei", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        name = Path(self._project_file).stem if self._project_file else "Projekt"
        if box.clickedButton() is b_zip:
            f, _ = QFileDialog.getSaveFileName(self, "ZIP speichern", str(Path.home() / f"{name}_gesammelt.zip"), "ZIP-Datei (*.zip)")
            if f:
                self.run_collect(f if f.lower().endswith(".zip") else f + ".zip", True, name)
        elif box.clickedButton() is b_dir:
            d = QFileDialog.getExistingDirectory(self, "Zielordner wählen", str(Path.home()))
            if d:
                target = Path(d) / f"{name}_gesammelt"
                n = 2
                while target.exists():
                    target = Path(d) / f"{name}_gesammelt_{n}"
                    n += 1
                self.run_collect(str(target), False, name)

    def run_collect(self, target: str, as_zip: bool, name: str = "Projekt", show_progress: bool = True) -> dict | None:
        """Kopiert die Dateien mit Fortschrittsanzeige; gibt das Ergebnis von collect() zurück, bei Abbruch/Fehler None."""
        dlg = None
        if show_progress:
            dlg = QProgressDialog("Dateien werden kopiert …", "Abbrechen", 0, 100, self)
            dlg.setWindowTitle(APP_NAME)
            dlg.setWindowModality(Qt.WindowModality.WindowModal)
            dlg.setMinimumDuration(0)
            dlg.setValue(0)

        def prog(frac: float, label: str):
            if dlg is not None:
                dlg.setValue(int(frac * 100))
                dlg.setLabelText(f"Wird kopiert: {label}")
                QApplication.processEvents()

        try:
            r = collectlib.collect(self.project, target, as_zip, name, prog, (lambda: dlg.wasCanceled()) if dlg is not None else None)
        except collectlib.Cancelled:
            self.statusBar().showMessage("Sammeln abgebrochen.")
            return None
        except Exception as exc:  # noqa: BLE001
            diagnostics.log_error("Projekt sammeln fehlgeschlagen: %s", exc)
            QMessageBox.critical(self, "Projekt sammeln", f"Das Sammeln ist fehlgeschlagen:\n{exc}")
            return None
        finally:
            if dlg is not None:
                dlg.close()
        msg = f"Projekt gesammelt: {r['files']} Datei(en) in {target}"
        if r["missing"]:
            msg += f" – {len(r['missing'])} fehlende Datei(en) übersprungen"
        self.statusBar().showMessage(msg)
        return r

    def save_project(self) -> None:
        f, _ = QFileDialog.getSaveFileName(self, "Projekt speichern", self._project_file or "Projekt.cforge", f"{APP_NAME}-Projekt (*.cforge)")
        if f:
            self.project.save(f)
            self._saved_state = self.project.to_json()
            self._remove_autosave()
            self._project_file = f
            self.statusBar().showMessage(f"Gespeichert: {f}")

    def open_project(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Projekt öffnen", "", f"{APP_NAME}-Projekt (*.cforge)")
        if not f:
            return
        try:
            self.project = Project.load(f)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Projekt öffnen", f"Datei konnte nicht gelesen werden:\n{exc}")
            return
        self._project_file = f
        self.asel = -1
        self.osel = -1
        self._sync_controls_from_project()
        self._refresh_timeline(select=0 if self.project.clips else -1)
        self._request_waveforms()
        state = self.project.to_json()
        self._history.reset(state)
        self._saved_state = state
        if self.project.missing_paths():
            self.relink_dialog()

    # --------------------------------------------------------------- Updates
    def check_updates(self, silent: bool) -> None:
        if not updater.configured():
            if not silent:
                QMessageBox.information(self, "Updates", "Der GitHub-Name ist noch nicht in app/version.py eingetragen.")
            return
        self._upd_worker = UpdateCheckWorker(self)

        def result(info, err):
            if err:
                if not silent:
                    QMessageBox.warning(self, "Updates", f"Update-Suche fehlgeschlagen:\n{err}")
                return
            if info is None:
                if not silent:
                    QMessageBox.information(self, "Updates", f"Du hast die neueste Version ({VERSION}).")
                return
            if QMessageBox.question(self, "Update verfügbar",
                                    f"Version {info.version} ist verfügbar (installiert: {VERSION}).\n\n{info.notes}\n\nJetzt herunterladen und installieren?") \
                    == QMessageBox.StandardButton.Yes:
                self._download_update(info)

        self._upd_worker.result.connect(result)
        self._upd_worker.start()

    def _download_update(self, info) -> None:
        dlg = QProgressDialog("Update wird heruntergeladen …", "Abbrechen", 0, 100, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        w = UpdateDownloadWorker(info, self)
        w.progress.connect(lambda p: dlg.setValue(int(p * 100)))

        def done(path: str, err: str):
            dlg.close()
            if err:
                QMessageBox.critical(self, "Update", f"Download fehlgeschlagen:\n{err}")
                return
            try:
                if not self._confirm_unsaved():          # ungespeicherte Änderungen: erst fragen, dann installieren
                    QMessageBox.information(self, "Update", f"Das Update ist heruntergeladen. Es wurde nicht installiert:\n{path}")
                    return
                if self._ask_on_close:
                    self._save_ui()
                updater.launch_installer(Path(path))     # startet das Programm nach der Installation selbst wieder
                QApplication.quit()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Update", str(exc))

        w.done.connect(done)
        self._dl_worker = w
        w.start()

    def _text_dialog(self, title: str, html: str = "", plain: str = "") -> QDialog:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(720, 640)
        lay = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        if html:
            tb.setHtml(html)
        else:
            tb.setPlainText(plain)
        lay.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)
        dlg._browser = tb
        return dlg

    # ---------------------------------------------------------- Spracherkennung einrichten
    def setup_whisper(self, then_run: bool = False) -> None:
        """Lädt whisper.cpp und ein Sprachmodell (nur was fehlt) – mit Fortschritt und Abbrechen."""
        from ..core import whisper_setup as ws
        if getattr(self, "_ws_worker", None) is not None:
            return
        if subs.find_whisper() is not None and not then_run:
            QMessageBox.information(self, "Spracherkennung", "Die Spracherkennung ist bereits eingerichtet.")
            return
        names = list(ws.MODELS)
        labels = [f"{n} – {ws.MODELS[n][2]} (ca. {ws.MODELS[n][1]} MB)" for n in names]
        if subs.find_whisper_model() is None:
            label, ok = QInputDialog.getItem(
                self, "Spracherkennung einrichten",
                f"Für automatische Untertitel lädt {APP_NAME} das kostenlose whisper.cpp und ein Sprachmodell herunter.\n"
                "Die Erkennung läuft danach komplett auf deinem PC.\n\nWelches Modell?", labels, 1, False)
            if not ok:
                return
            model = names[labels.index(label)]
        else:
            model = "base"
        dlg = QProgressDialog("Wird vorbereitet …", "Abbrechen", 0, 100, self)
        dlg.setWindowTitle("Spracherkennung einrichten")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        w = WhisperSetupWorker(model, self)
        w.progress.connect(lambda t, f: (dlg.setLabelText(t), dlg.setValue(int(f * 100))))
        dlg.canceled.connect(w.cancel)

        def done(err: str) -> None:
            dlg.close()
            self._ws_worker = None
            if err == "abgebrochen":
                return
            if err:
                diagnostics.log_error("Whisper-Einrichtung fehlgeschlagen: %s", err)
                r = QMessageBox.question(
                    self, "Spracherkennung",
                    f"Das Herunterladen hat nicht geklappt:\n{err}\n\nDu kannst die Dateien auch selbst in den Ordner legen:\n"
                    f"{subs.whisper_dir()}\n(whisper-cli.exe mit DLLs und ein Modell wie ggml-base.bin).\n\nOrdner öffnen?")
                if r == QMessageBox.StandardButton.Yes:
                    self._open_folder(str(subs.whisper_dir()))
                return
            diagnostics.log("Spracherkennung eingerichtet (%s)", model)
            if then_run:
                self.auto_subtitles()
            else:
                QMessageBox.information(self, "Spracherkennung", "Fertig. Du kannst jetzt im Tab Untertitel automatisch erzeugen.")

        w.done.connect(done)
        self._ws_worker = w
        w.start()

    # ---------------------------------------------------------- Diagnose und Fehlerbericht
    def _report_dialog(self, title: str, text: str) -> QDialog:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(760, 620)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        edit.setPlainText(text)
        lay.addWidget(edit)
        row = QHBoxLayout()
        b_copy = QPushButton("Bericht kopieren")
        b_copy.clicked.connect(lambda: (QApplication.clipboard().setText(edit.toPlainText()),
                                        self.statusBar().showMessage("Bericht kopiert – füge ihn in die Nachricht ein.", 5000)))
        b_dir = QPushButton("Protokoll-Ordner öffnen")
        b_dir.clicked.connect(lambda: self._open_folder(str(diagnostics.log_dir())))
        b_close = QPushButton("Schließen")
        b_close.clicked.connect(dlg.accept)
        row.addWidget(b_copy)
        row.addWidget(b_dir)
        row.addStretch(1)
        row.addWidget(b_close)
        lay.addLayout(row)
        dlg._edit = edit
        return dlg

    def show_diagnostics(self) -> None:
        dlg = self._report_dialog("Diagnose und Fehlerbericht", "Diagnose läuft (Encoder werden kurz getestet) …")
        w = DiagnoseWorker(self)
        w.done.connect(dlg._edit.setPlainText)
        self._diag_worker = w
        w.start()
        dlg.exec()

    def show_crash(self, text: str) -> None:
        """Wird bei einem unerwarteten Fehler aufgerufen (aus jedem Thread über ein Signal)."""
        if os.environ.get("CLIPFORGE_NO_PROMPTS") or getattr(self, "_crash_open", False):
            return
        self._crash_open = True
        try:
            report = diagnostics.build_report(with_encoder_test=False, with_log=False) + "\n\n" + text
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Unerwarteter Fehler")
            box.setText(f"Hier ist etwas schiefgelaufen. {APP_NAME} läuft weiter; speichere sicherheitshalber dein Projekt.\n\n"
                        "Mit „Bericht kopieren“ kannst du den Fehler weitergeben.")
            box.setDetailedText(text)
            b_copy = box.addButton("Bericht kopieren", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Schließen", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is b_copy:
                QApplication.clipboard().setText(report)
        finally:
            self._crash_open = False

    def show_help(self) -> None:
        self._text_dialog("Kurzanleitung", html=help_html()).exec()

    def show_licenses(self) -> None:
        f = paths.bundle_dir() / "THIRD_PARTY.txt"
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            text = "Die Lizenzdatei wurde nicht gefunden."
        self._text_dialog("Lizenzen und Drittanbieter-Software", plain=text).exec()

    def about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"Über {APP_NAME}")
        box.setText(f"<b>{APP_NAME}</b> {VERSION}<br>Videoschnitt mit Presets für YouTube, Shorts, TikTok und Reels.<br><br>"
                    "Nutzt FFmpeg (ffmpeg.org) zum Rendern.<br>Details: Hilfe → Lizenzen und Drittanbieter-Software.")
        logo = paths.bundle_dir() / "assets" / "logo.png"
        if logo.exists():
            pm = QPixmap(str(logo))
            if not pm.isNull():
                box.setIconPixmap(pm.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        box.exec()

    def _confirm_unsaved(self) -> bool:
        """Fragt bei ungespeicherten Änderungen nach dem Speichern; False = der Benutzer will doch nicht beenden."""
        if self._ask_on_close and (self.project.clips or self.project.audio_clips or self.project.overlays or self.project.subtitles) and self._is_dirty():
            box = QMessageBox.question(
                self, APP_NAME, "Es gibt ungespeicherte Änderungen. Projekt speichern?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if box == QMessageBox.StandardButton.Cancel:
                return False
            if box == QMessageBox.StandardButton.Save:
                self.save_project()
                if self._is_dirty():          # Speichern-Dialog abgebrochen
                    return False
        return True

    # ------------------------------------------------------------- Tastenkürzel
    EDIT_KEYS = {"S": "s", "M": "m", "Escape": "esc", "Left": "left", "Right": "right", "Home": "home", "End": "end"}   # Entf und Leertaste sind Menü-Aktionen

    def _edit_keys_ok(self) -> bool:
        """Die Schnitt-Tasten gelten nicht, solange in einem Eingabefeld, einer Liste, einem Auswahlfeld oder Regler getippt wird."""
        fw = QApplication.focusWidget()
        if fw is None:
            return True
        return not isinstance(fw, (QLineEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox, QAbstractItemView, QSlider))

    def _frame_step(self) -> float:
        f = presets.get("formats", self.project.format_id) or {}
        return 1.0 / max(1.0, float(f.get("fps", 30)))

    def edit_key(self, name: str, shift: bool = False) -> bool:
        """Führt eine Schnitt-Taste aus (s, delete, left, right, home, end, space); True, wenn sie etwas bewirkt hat."""
        if not self.project.clips:
            return False
        now = max(0.0, self.timeline.playhead)
        if name == "s":
            self.split_clip()
        elif name == "delete":
            self.delete_selected()
        elif name in ("left", "right"):
            step = 1.0 if shift else self._frame_step()
            self._seek_project(max(0.0, min(self.project.duration - 0.01, now + (step if name == "right" else -step))))
        elif name == "esc":
            if not self.timeline.multi_items():
                return False
            self.timeline.clear_multi()
            self.statusBar().showMessage("Auswahl aufgehoben.")
        elif name == "m":
            self.add_marker()
        elif name in ("prev_marker", "next_marker"):
            self.goto_marker(1 if name == "next_marker" else -1)
        elif name == "home":
            self._seek_project(0.0)
        elif name == "end":
            self._seek_project(max(0.0, self.project.duration - 0.05))
        elif name == "space":
            self.toggle_play()
        else:
            return False
        return True

    def keyPressEvent(self, event):  # noqa: N802
        mods = event.modifiers()
        plain = not (mods & ~Qt.KeyboardModifier.ShiftModifier)
        name = None
        for key_name, short in self.EDIT_KEYS.items():
            if event.key() == getattr(Qt.Key, "Key_" + key_name):
                name = short
        shift_ok = name in ("left", "right")
        if name and plain and self._edit_keys_ok() and (shift_ok or not (mods & Qt.KeyboardModifier.ShiftModifier)):
            if self.edit_key(name, bool(mods & Qt.KeyboardModifier.ShiftModifier)):
                event.accept()
                return
        if (mods == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right)
                and self._edit_keys_ok()):
            if self.edit_key("next_marker" if event.key() == Qt.Key.Key_Right else "prev_marker"):
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self._confirm_unsaved():
            event.ignore()
            return
        if self._ask_on_close:
            self._save_ui()
        self._hist_timer.stop()
        self._autosave_timer.stop()
        self._live_timer.stop()
        if self._track_worker is not None:
            self._track_worker.cancel()
            self._track_worker.wait(3000)
        if self._stab_worker is not None:
            self._stab_worker.cancel()
            self._stab_worker.wait(3000)
        for tw in list(self._thumb_workers) + list(self._frame_workers):
            tw.wait(2000)
        if self._live_worker is not None:
            self._live_worker.cancel()
            self._live_worker.wait(3000)
        self._remove_autosave()
        if self._grade_worker is not None:
            self._grade_worker.wait(3000)
        for w in self._wave_workers:
            w.wait(3000)
        if self._asr_worker is not None:
            self._asr_worker.wait(3000)
        try:
            self.player.stop()
        finally:
            for d in self._tmp_dirs:
                shutil.rmtree(d, ignore_errors=True)
        super().closeEvent(event)
