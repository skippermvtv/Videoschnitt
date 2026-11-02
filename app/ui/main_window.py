"""Hauptfenster von FATE VIDEOSCHNITT."""
from __future__ import annotations

import copy
import os
import shutil
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QKeySequence, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox, QTextBrowser, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QSlider,
    QFrame, QScrollArea, QSizePolicy, QSplitter, QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import paths
from ..core import effects as fx
from ..core import diagnostics, exporter, grade as gradelib, preview as prevcache, presets, settings, subtitles as subs, updater
from ..core.history import History
from ..core.fontcheck import missing_chars
from ..core.helptext import help_html
from ..core.project import (IMAGE_MAX, OVERLAY_CORNERS, TRACK_NAMES, AudioClip, Clip, MediaInfo, OverlayClip,
                            TEXT_ANIMS, Project, SubtitleCue, TextLayer, is_image_path, probe, probe_audio)
from ..version import APP_NAME, VERSION
from .theme import ACCENT, MUTED
from .timeline import FX_MIME, Timeline
from .workers import ExportWorker, GradePreviewWorker, UpdateCheckWorker, UpdateDownloadWorker, WaveformWorker, AsrWorker, WhisperSetupWorker, DiagnoseWorker

VIDEO_FILTER = ("Videos und Bilder (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.mts *.m2ts "
                "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff);;Alle Dateien (*)")
LAYOUTS = [("", "Automatisch (vom Format)"), ("fit", "Einpassen (schwarze Balken)"),
           ("fill", "Füllen (zuschneiden)"), ("blur", "Unscharfer Hintergrund")]
AUDIO_FILTER = ("Audio und Videos (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mov *.mkv *.webm);;"
                "Alle Dateien (*)")
FX_TAB = 2
AUDIO_TAB = 5
OVERLAY_TAB = 6
SUBTITLE_TAB = 7
MOTION_TAB = 8
SRT_FILTER = "Untertitel (*.srt);;Alle Dateien (*)"
ASR_LANGS = [("auto", "Automatisch erkennen"), ("de", "Deutsch"), ("en", "Englisch"), ("pl", "Polnisch"),
             ("es", "Spanisch"), ("fr", "Französisch"), ("it", "Italienisch"), ("tr", "Türkisch"), ("ru", "Russisch")]
TEXT_POS = [("top", "Oben"), ("center", "Mitte"), ("bottom", "Unten")]


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


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
        self._preview_path = ""        # Datei, die gerade als Vorschau läuft
        self._preview_start = 0.0
        self._job_t0 = 0.0
        self._sub_color = "#ffffff"
        self._fonts: dict[str, str] = {}
        self.fsel = -1          # gewählter Effekt-Block auf der FX-Spur
        self._text_color = "#ffffff"
        self._cur_path = ""
        self._pending_seek: int | None = None
        self._autoplay = False
        self._limit_ms: int | None = None
        self._project_file = ""
        self._worker = None
        self._tmp_dirs: list[Path] = []
        self._grade_worker = None
        self._grade_dirty = False
        self._grade_sliders: dict[str, QSlider] = {}
        self._grade_labels: dict[str, QLabel] = {}
        self._grade_timer = QTimer(self)
        self._grade_timer.setSingleShot(True)
        self._grade_timer.setInterval(250)
        self._grade_timer.timeout.connect(self._update_grade_preview)

        self._history = History(self.project.to_json())
        self._saved_state = self.project.to_json()
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
        prevcache.cleanup()
        self._hist_timer.start()
        self._autosave_timer.start()
        if self._ask_on_close:
            QTimer.singleShot(900, self._offer_restore)
        if updater.configured():
            QTimer.singleShot(2500, lambda: self.check_updates(silent=True))

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
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split)

        # -- links: Medien
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        brand = QLabel(APP_NAME)
        brand.setWordWrap(True)            # „FATE VIDEOSCHNITT“ passt in zwei Zeilen
        f = QFont(getattr(self, "_brand_family", self.font().family()))
        f.setPointSize(22)
        brand.setFont(f)
        brand.setStyleSheet(f"color: {ACCENT};")
        lv.addWidget(brand)
        lv.addWidget(QLabel("Medien (Dateien auch hierher ziehen)"))
        self.media_list = QListWidget()
        self.media_list.itemDoubleClicked.connect(lambda it: self._add_to_timeline(it.data(Qt.ItemDataRole.UserRole)))
        self.media_list.currentItemChanged.connect(self._on_media_selected)
        lv.addWidget(self.media_list, 1)
        b1 = QPushButton("Dateien importieren …")
        b1.clicked.connect(self.import_dialog)
        b2 = QPushButton("Zur Timeline hinzufügen  ▶")
        b2.clicked.connect(self._add_selected_media)
        lv.addWidget(b1)
        lv.addWidget(b2)
        left.setMinimumWidth(230)
        split.addWidget(left)

        # -- Mitte: Vorschau + Timeline
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        self.video = QVideoWidget()
        self.video.setMinimumSize(420, 240)
        self.video.setStyleSheet("background: black;")
        mv.addWidget(self.video, 1)

        self.audio = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, int(d)))
        self.player.mediaStatusChanged.connect(self._on_media_status)

        tr = QHBoxLayout()
        self.btn_play = QPushButton("▶ / ❚❚")
        self.btn_play.setFixedWidth(80)
        self.btn_play.clicked.connect(self.toggle_play)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.time_label = QLabel("0:00.0")
        self.time_label.setFixedWidth(60)
        tr.addWidget(self.btn_play)
        tr.addWidget(self.seek, 1)
        tr.addWidget(self.time_label)
        mv.addLayout(tr)

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
        self.timeline.effect_dropped.connect(self._on_fx_dropped)
        mv.addWidget(self.timeline)

        cb = QHBoxLayout()
        for text, slot in (("✂ Am Abspielkopf teilen", self.split_clip), ("◀ Nach links", lambda: self.move_clip(-1)),
                           ("Nach rechts ▶", lambda: self.move_clip(1)), ("Clip löschen", self.delete_clip)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            cb.addWidget(b)
        cb.addStretch(1)
        self.dur_label = QLabel("Gesamtlänge: 0:00.0")
        self.dur_label.setStyleSheet(f"color: {MUTED};")
        cb.addWidget(self.dur_label)
        mv.addLayout(cb)
        ab = QHBoxLayout()
        for text, slot in (("♪ Ton vom Clip trennen", self.detach_selected_audio),
                           ("♫ Musik / Audio hinzufügen …", self.add_audio_dialog),
                           ("▣ Bild-in-Bild hinzufügen …", self.add_overlay_dialog),
                           ("Audioblock löschen", self.remove_audio)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            ab.addWidget(b)
        ab.addStretch(1)
        for text, slot in (("＋", lambda: self.timeline.zoom_by(1.5)), ("−", lambda: self.timeline.zoom_by(1 / 1.5)),
                           ("Alles zeigen", self.timeline.zoom_fit)):
            b = QPushButton(text)
            b.setToolTip("Timeline zoomen (auch Strg + Mausrad)")
            b.clicked.connect(slot)
            ab.addWidget(b)
        mv.addLayout(ab)
        split.addWidget(mid)

        # -- rechts: Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_format_tab(), "Format")
        self.tabs.addTab(self._build_grade_tab(), "Bild")
        self.tabs.addTab(self._build_effects_tab(), "Effekte")
        self.tabs.addTab(self._build_text_tab(), "Text")
        self.tabs.addTab(self._build_clip_tab(), "Clip")
        self.tabs.addTab(self._build_audio_tab(), "Ton")
        self.tabs.addTab(self._build_overlay_tab(), "Bild-in-Bild")
        self.tabs.addTab(self._build_subtitle_tab(), "Untertitel")
        self.tabs.addTab(self._build_motion_tab(), "Bewegung")
        self.tabs.setMinimumWidth(400)
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([240, 860, 380])

        self.statusBar().showMessage("Bereit. Ziehe Videodateien ins Fenster, um zu starten.")

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
            other.grade = dict(c.grade)
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
        w = GradePreviewWorker(c.path, t, dict(c.grade), self)
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
        self.clip_mute = QCheckBox("Ton stummschalten")
        self.clip_mute.toggled.connect(self._on_clip_field)
        self.clip_rev = QCheckBox("Rückwärts abspielen (nur kurze Clips)")
        self.clip_rev.toggled.connect(self._on_clip_field)
        form.addRow(self.clip_name)
        form.addRow("Start im Clip", self.clip_in)
        form.addRow("Ende im Clip", self.clip_out)
        form.addRow("Geschwindigkeit", self.clip_speed)
        form.addRow("Lautstärke", vr)
        form.addRow(self.clip_mute)
        self.clip_audio_note = QLabel("Der Ton dieses Clips liegt als eigener Block auf A1 (Registerkarte „Ton“).")
        self.clip_audio_note.setWordWrap(True)
        self.clip_audio_note.setStyleSheet(f"color: {MUTED};")
        self.clip_audio_note.setVisible(False)
        form.addRow(self.clip_audio_note)
        form.addRow(self.clip_rev)
        hint = QLabel("Zeitlupe: Geschwindigkeit unter 1, Zeitraffer: über 1.")
        hint.setStyleSheet(f"color: {MUTED};")
        form.addRow(hint)
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
        form.addRow(QLabel("Übergang zum nächsten Clip"))
        form.addRow("Art", self.clip_trans)
        form.addRow("Dauer", self.clip_trans_dur)
        form.addRow(btn_all)
        form.addRow(self.clip_trans_note)
        self.clip_tab = w
        w.setEnabled(False)
        return w

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
        form.addRow("Einblenden", self.aud_fin)
        form.addRow("Ausblenden", self.aud_fout)
        self.aud_loop = QCheckBox("Wiederholen, bis das Video endet")
        self.aud_mute = QCheckBox("Stummschalten")
        self.aud_rev = QCheckBox("Rückwärts")
        for cb in (self.aud_loop, self.aud_mute, self.aud_rev):
            cb.toggled.connect(self._on_audio_field)
            form.addRow(cb)
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
        self.mix_norm = QCheckBox("Lautheit angleichen (−14 LUFS, wie YouTube/TikTok)")
        self.mix_norm.toggled.connect(self._on_mix_field)
        mf.addRow(self.mix_norm)
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
        self.ov_fin = dspin(0.0, 30.0, 0.1)
        self.ov_fout = dspin(0.0, 30.0, 0.1)
        form.addRow("Mitte waagerecht", self.ov_x)
        form.addRow("Mitte senkrecht", self.ov_y)
        form.addRow("Größe (Breite)", self.ov_size)
        form.addRow("Deckkraft", self.ov_opacity)
        form.addRow("Einblenden", self.ov_fin)
        form.addRow("Ausblenden", self.ov_fout)
        self.ov_border = QCheckBox("Weißer Rahmen")
        self.ov_border.toggled.connect(self._on_overlay_field)
        form.addRow(self.ov_border)
        b1 = QPushButton("Bild-in-Bild löschen")
        b1.clicked.connect(self.remove_overlay)
        form.addRow(b1)
        self.ov_group.setEnabled(False)
        v.addWidget(self.ov_group)
        v.addStretch(1)
        return outer

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
        tb = QToolBar("Hauptleiste")
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, slot, shortcut=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            return a

        self.act_open = act("Projekt öffnen", self.open_project, "Ctrl+O")
        self.act_save = act("Projekt speichern", self.save_project, "Ctrl+S")
        self.act_preview = act("▶ Vorschau ab Abspielkopf", self.render_preview, "Ctrl+P")
        self.act_export = act("Exportieren …", self.export_video, "Ctrl+E")
        self.act_undo = act("↶ Rückgängig", self.undo, "Ctrl+Z")
        self.act_redo = act("↷ Wiederholen", self.redo)
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        for a in (self.act_open, self.act_save, self.act_undo, self.act_redo):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_preview)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        btn = QPushButton("Exportieren …")
        btn.setObjectName("primary")
        btn.clicked.connect(self.export_video)
        tb.addWidget(btn)

        me = self.menuBar().addMenu("Bearbeiten")
        me.addAction(self.act_undo)
        me.addAction(self.act_redo)
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
        self.fx_box.setEnabled(ok)
        self.btn_fx_del.setEnabled(ok)
        if not ok:
            self.fx_box.setTitle("Gewählter Effekt-Block (keiner gewählt – in der Timeline anklicken)")
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
            it = QListWidgetItem(f"{Path(f).name}   ({kind}, {info.width}×{info.height})")
            it.setData(Qt.ItemDataRole.UserRole, f)
            self.media_list.addItem(it)
        if errors:
            QMessageBox.warning(self, "Import", "Nicht alle Dateien konnten gelesen werden:\n\n" + "\n".join(errors))
        if files and not self.project.clips and files[0] in self.media:
            self._add_to_timeline(files[0])

    def _on_media_selected(self, item, _prev) -> None:
        if item:
            self._open_media(item.data(Qt.ItemDataRole.UserRole), 0, None, autoplay=False)

    def _add_selected_media(self) -> None:
        it = self.media_list.currentItem()
        if it:
            self._add_to_timeline(it.data(Qt.ItemDataRole.UserRole))

    def _add_to_timeline(self, path: str) -> None:
        info = self.media.get(path)
        if not info:
            return
        if info.is_image:
            clip = Clip(path, IMAGE_MAX, out_pt=info.duration, has_audio=False, width=info.width,
                        height=info.height, is_image=True)
        else:
            clip = Clip(path, info.duration, has_audio=info.has_audio, width=info.width, height=info.height)
        self.project.clips.append(clip)
        self._refresh_timeline(select=len(self.project.clips) - 1)

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
        self.dur_label.setText(f"Gesamtlänge: {fmt_time(self.project.duration)}")
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
        last = self.sel >= len(self.project.clips) - 1
        self.clip_trans.setCurrentIndex(max(0, self.clip_trans.findData(c.transition)))
        self.clip_trans_dur.setValue(c.transition_dur)
        self.clip_trans.setEnabled(not last)
        self.clip_trans_dur.setEnabled(not last)
        self.clip_trans_note.setVisible(last)
        self._loading = False
        self._load_grade_fields()
        self._load_motion_fields()

    def _on_clip_field(self, *_args) -> None:
        self.clip_vol_label.setText(f"{self.clip_vol.value()} %")
        if self._loading or not (0 <= self.sel < len(self.project.clips)):
            return
        c = self.project.clips[self.sel]
        c.in_pt = min(self.clip_in.value(), self.clip_out.value() - 0.05)
        c.out_pt = max(self.clip_out.value(), c.in_pt + 0.05)
        c.speed = self.clip_speed.value()
        c.volume = self.clip_vol.value() / 100.0
        c.mute = self.clip_mute.isChecked()
        c.reverse = self.clip_rev.isChecked()
        c.transition = str(self.clip_trans.currentData() or "")
        c.transition_dur = self.clip_trans_dur.value()
        self.project.sync_linked()
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self.dur_label.setText(f"Gesamtlänge: {fmt_time(self.project.duration)}")

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

    def pick_sub_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._sub_color), self, "Untertitel-Farbe")
        if c.isValid():
            self._sub_color = c.name()
            self.btn_sub_color.setStyleSheet(f"background: {self._sub_color}; color: black; font-weight: 600;")
            self._on_sub_style()

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
        self.btn_asr.setEnabled(True)
        self.btn_asr.setText("Untertitel automatisch erzeugen")
        if err or cues is None:
            QMessageBox.warning(self, "Untertitel", err or "Es wurde nichts erkannt.")
            return
        self.project.subtitles = subs.split_long(cues)
        self._load_sub_list(0 if self.project.subtitles else -1)
        self.statusBar().showMessage(f"{len(self.project.subtitles)} Untertitel erkannt – bitte kurz prüfen und korrigieren.")

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
        self.ov_fin.setValue(o.fade_in)
        self.ov_fout.setValue(o.fade_out)
        self.ov_border.setChecked(o.border)
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
        o.fade_in = self.ov_fin.value()
        o.fade_out = self.ov_fout.value()
        o.border = self.ov_border.isChecked()
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
        self.aud_fin.setValue(a.fade_in)
        self.aud_fout.setValue(a.fade_out)
        self.aud_loop.setChecked(a.loop)
        self.aud_mute.setChecked(a.mute)
        self.aud_rev.setChecked(a.reverse)
        self.btn_aud_reattach.setEnabled(a.kind == "video")
        self._loading = False

    def _on_audio_field(self, *_args) -> None:
        self.aud_vol_label.setText(f"{self.aud_vol.value()} %")
        a = self._selected_audio()
        if self._loading or a is None:
            return
        a.track = int(self.aud_track.currentData() or 2)
        a.start = self.aud_start.value()
        a.in_pt = min(self.aud_in.value(), self.aud_out.value() - 0.05)
        a.out_pt = max(self.aud_out.value(), a.in_pt + 0.05)
        a.speed = self.aud_speed.value()
        a.volume = self.aud_vol.value() / 100.0
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
        self.mix_duck_amount.setEnabled(p.ducking)
        self._loading = False

    def _on_mix_field(self, *_args) -> None:
        for t in (1, 2, 3):
            self._mix_labels[t].setText(f"{self._mix_sliders[t].value()} %")
        self.mix_duck_label.setText(f"{self.mix_duck_amount.value()} %")
        self.mix_duck_amount.setEnabled(self.mix_duck.isChecked())
        if self._loading:
            return
        p = self.project
        for t in (1, 2, 3):
            p.track_volume[str(t)] = self._mix_sliders[t].value() / 100.0
            p.track_mute[str(t)] = self._mix_mutes[t].isChecked()
        p.ducking = self.mix_duck.isChecked()
        p.ducking_amount = self.mix_duck_amount.value() / 100.0
        p.normalize = self.mix_norm.isChecked()
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

    def delete_selected(self) -> None:
        if self.fsel >= 0:
            self.remove_effect_block()
        elif self.osel >= 0:
            self.remove_overlay()
        elif self.asel >= 0:
            self.remove_audio()
        else:
            self.delete_clip()

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
        name = Path(self._project_file).name if self._project_file else "Neues Projekt"
        self.setWindowTitle(f"{name}{' *' if state != self._saved_state else ''} – {APP_NAME} {VERSION}")
        self.act_undo.setEnabled(self._history.can_undo())
        self.act_redo.setEnabled(self._history.can_redo())

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
        self.dur_label.setText(f"Gesamtlänge: {fmt_time(self.project.duration)}")
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)

    def _reorder_clip(self, src: int, dst: int) -> None:
        cl = self.project.clips
        if 0 <= src < len(cl) and 0 <= dst < len(cl) and src != dst:
            cl.insert(dst, cl.pop(src))
            self._refresh_timeline(select=dst)

    def _seek_project(self, t: float) -> None:
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
        self._open_media(c.path, src_ms, int(c.out_pt * 1000), autoplay=False)
        self.timeline.set_project(self.project, self.sel, self.asel, self.osel, self.fsel)
        self.timeline.set_playhead(t)

    # --------------------------------------------------------------- Player
    def _open_media(self, path: str, seek_ms: int, limit_ms: int | None, autoplay: bool) -> None:
        if is_image_path(path):          # Bilder zeigt der Player nicht – Ergebnis siehe „Vorschau mit Effekten“
            self.player.stop()
            self._cur_path = ""
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

    def _on_position(self, pos: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(int(pos))
        self.time_label.setText(fmt_time(pos / 1000.0))
        if self._preview_path and self._cur_path == self._preview_path:
            self.timeline.set_playhead(self._preview_start + pos / 1000.0)
        elif 0 <= self.sel < len(self.project.clips):
            c = self.project.clips[self.sel]
            if c.path == self._cur_path:
                rel = (pos / 1000.0 - c.in_pt) / max(c.speed, 0.01)
                if -0.05 <= rel <= c.length + 0.05:
                    self.timeline.set_playhead(self.project.clip_start(self.sel) + max(0.0, rel))
        if self._limit_ms is not None and pos >= self._limit_ms:
            self.player.pause()

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            return
        if self._limit_ms is not None and self.player.position() >= self._limit_ms - 50 and 0 <= self.sel < len(self.project.clips):
            self.player.setPosition(int(self.project.clips[self.sel].in_pt * 1000))
        self.player.play()

    # ---------------------------------------------------------- Export/Vorschau
    def _run_job(self, cmd, total, title: str, on_done) -> None:
        dlg = QProgressDialog(title, "Abbrechen", 0, 100, self)
        dlg.setWindowTitle(APP_NAME)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        worker = ExportWorker(cmd, total, self)
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
        problems = [(t, missing_chars(t.font, t.text)) for t in self.project.texts]
        problems = [(t, m) for t, m in problems if m]
        if problems:
            detail = "\n".join(f"„{self._text_title(t)}“: {' '.join(m)}" for t, m in problems)
            if QMessageBox.question(self, "Fehlende Zeichen in der Schrift",
                                    "Diese Zeichen gibt es in der gewählten Schrift nicht und sie bleiben im Video leer:\n\n"
                                    f"{detail}\n\nTrotzdem exportieren?") != QMessageBox.StandardButton.Yes:
                return
        out, _ = QFileDialog.getSaveFileName(self, "Video exportieren", str(Path.home() / "Mein_Video.mp4"), "MP4-Video (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        use_hw = self.chk_hw.isChecked() and exporter.hw_encoder() is not None
        self._start_export(out, use_hw)

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
                self.statusBar().showMessage(f"Export fertig: {out}" + (" (mit Grafikkarte)" if use_hw else ""))
                if QMessageBox.question(self, "Export fertig", f"Gespeichert unter:\n{out}\n\nOrdner öffnen?") == QMessageBox.StandardButton.Yes:
                    self._open_folder(str(Path(out).parent))

        self._run_job(cmd, total, "Video wird exportiert …", done)

    def _on_perf_changed(self, *_args) -> None:
        settings.save({"preview_len": float(self.cmb_prev_len.currentData() or 0.0),
                       "preview_height": int(self.cmb_prev_q.currentData() or 360),
                       "hw_encode": bool(self.chk_hw.isChecked())})

    def render_preview(self) -> None:
        if not self._check_ready():
            return
        start = max(0.0, self.timeline.playhead)
        if start >= self.project.duration - 0.5:
            start = 0.0
        length = float(self.cmb_prev_len.currentData() or 0.0)
        height = int(self.cmb_prev_q.currentData() or 360)
        target = prevcache.path_for(self.project, start, length, height)

        def play(path: Path):
            self._cur_path = ""
            self._open_media(str(path), 0, None, autoplay=True)
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
                updater.launch_installer(Path(path))
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

    def closeEvent(self, event):
        if self._ask_on_close and (self.project.clips or self.project.audio_clips or self.project.overlays or self.project.subtitles) and self._is_dirty():
            box = QMessageBox.question(
                self, APP_NAME, "Es gibt ungespeicherte Änderungen. Projekt speichern?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if box == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if box == QMessageBox.StandardButton.Save:
                self.save_project()
                if self._is_dirty():          # Speichern-Dialog abgebrochen
                    event.ignore()
                    return
        self._hist_timer.stop()
        self._autosave_timer.stop()
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
