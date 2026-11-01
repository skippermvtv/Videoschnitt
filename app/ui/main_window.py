"""Hauptfenster von ClipForge."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QSlider,
    QSizePolicy, QSplitter, QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import paths
from ..core import effects as fx
from ..core import exporter, presets, updater
from ..core.project import Clip, MediaInfo, Project, TextLayer, probe
from ..version import APP_NAME, VERSION
from .theme import ACCENT, MUTED
from .timeline import Timeline
from .workers import ExportWorker, UpdateCheckWorker, UpdateDownloadWorker

VIDEO_FILTER = "Videos (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.mts *.m2ts);;Alle Dateien (*)"
LAYOUTS = [("", "Automatisch (vom Format)"), ("fit", "Einpassen (schwarze Balken)"),
           ("fill", "Füllen (zuschneiden)"), ("blur", "Unscharfer Hintergrund")]
TEXT_POS = [("top", "Oben"), ("center", "Mitte"), ("bottom", "Unten")]


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = Project()
        self.media: dict[str, MediaInfo] = {}
        self.sel = -1
        self._loading = False
        self._fonts: dict[str, str] = {}
        self._fx_state: dict[str, dict] = {
            e.id: {"intensity": e.default, "start": 0.0, "end": 0.0} for e in fx.REGISTRY.values()}
        self._text_color = "#ffffff"
        self._cur_path = ""
        self._pending_seek: int | None = None
        self._autoplay = False
        self._limit_ms: int | None = None
        self._project_file = ""
        self._worker = None
        self._tmp_dirs: list[Path] = []

        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.resize(1480, 880)
        self.setAcceptDrops(True)
        self._load_fonts()
        self._build_ui()
        self._build_actions()
        self._populate_presets()
        self._sync_controls_from_project()
        self._refresh_timeline()
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
        f = QFont(getattr(self, "_brand_family", self.font().family()))
        f.setPointSize(26)
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
        split.addWidget(mid)

        # -- rechts: Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_format_tab(), "Format")
        self.tabs.addTab(self._build_effects_tab(), "Effekte")
        self.tabs.addTab(self._build_text_tab(), "Text")
        self.tabs.addTab(self._build_clip_tab(), "Clip")
        self.tabs.setMinimumWidth(350)
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

        self.fx_tree = QTreeWidget()
        self.fx_tree.setHeaderHidden(True)
        for cat, items in fx.categories().items():
            top = QTreeWidgetItem([cat])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.fx_tree.addTopLevelItem(top)
            for e in items:
                it = QTreeWidgetItem([e.name])
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                it.setCheckState(0, Qt.CheckState.Unchecked)
                it.setData(0, Qt.ItemDataRole.UserRole, e.id)
                top.addChild(it)
            top.setExpanded(True)
        self.fx_tree.itemChanged.connect(lambda *_: self._collect_effects())
        self.fx_tree.currentItemChanged.connect(self._on_fx_selected)
        v.addWidget(self.fx_tree, 1)

        self.fx_box = QGroupBox("Einstellungen")
        fl = QFormLayout(self.fx_box)
        self.fx_int = QSlider(Qt.Orientation.Horizontal)
        self.fx_int.setRange(0, 100)
        self.fx_int.valueChanged.connect(self._on_fx_param)
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
            sp.valueChanged.connect(self._on_fx_param)
        fl.addRow("Nur ab", self.fx_start)
        fl.addRow("… bis (0 = Ende)", self.fx_end)
        self.fx_box.setEnabled(False)
        v.addWidget(self.fx_box)
        hint = QLabel("Haken setzen = Effekt an. Mit „Nur ab / bis“ wirkt ein Effekt nur in einem Zeitfenster (z. B. Glitch-Intro).")
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
        self.text_box.setEnabled(False)
        v.addWidget(self.text_box)
        v.addStretch(1)
        self._refresh_font_combo()
        return w

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
        form.addRow(self.clip_rev)
        hint = QLabel("Zeitlupe: Geschwindigkeit unter 1, Zeitraffer: über 1.")
        hint.setStyleSheet(f"color: {MUTED};")
        form.addRow(hint)
        self.clip_tab = w
        w.setEnabled(False)
        return w

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
        self.act_preview = act("Vorschau mit Effekten (8 s)", self.render_preview, "Ctrl+P")
        self.act_export = act("Exportieren …", self.export_video, "Ctrl+E")
        for a in (self.act_open, self.act_save):
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

        m = self.menuBar().addMenu("Hilfe")
        m.addAction(act("Nach Updates suchen", lambda: self.check_updates(silent=False)))
        m.addAction(act("Eigene Presets-Ordner öffnen", self.open_presets_folder))
        m.addAction(act("Über", self.about))

        self.act_play = act("Abspielen/Pause", self.toggle_play, "Space")
        self.addAction(self.act_play)
        self.act_del = act("Clip löschen", self.delete_clip, "Delete")
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
        # Effekte
        active = {e["id"]: e for e in p.effects}
        for it in self._fx_items():
            eid = it.data(0, Qt.ItemDataRole.UserRole)
            if eid in active:
                e = active[eid]
                self._fx_state[eid] = {"intensity": e.get("intensity", 50),
                                       "start": e.get("start") or 0.0, "end": e.get("end") or 0.0}
                it.setCheckState(0, Qt.CheckState.Checked)
            else:
                it.setCheckState(0, Qt.CheckState.Unchecked)
        # Texte
        self.text_list.clear()
        for t in p.texts:
            self.text_list.addItem(self._text_title(t))
        self._loading = False
        self._update_format_info()

    def _fx_items(self):
        for ci in range(self.fx_tree.topLevelItemCount()):
            cat = self.fx_tree.topLevelItem(ci)
            for j in range(cat.childCount()):
                yield cat.child(j)

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
        self._loading = True
        for it in self._fx_items():
            it.setCheckState(0, Qt.CheckState.Unchecked)
        for entry in look.get("effects", []):
            eid, intensity = entry[0], entry[1]
            start = entry[2] if len(entry) > 2 else 0.0
            end = entry[3] if len(entry) > 3 else 0.0
            if eid not in self._fx_state:
                continue
            self._fx_state[eid] = {"intensity": intensity, "start": float(start), "end": float(end)}
            for it in self._fx_items():
                if it.data(0, Qt.ItemDataRole.UserRole) == eid:
                    it.setCheckState(0, Qt.CheckState.Checked)
        self._loading = False
        self.project.look_id = look["id"]
        self._collect_effects()
        self._on_fx_selected(self.fx_tree.currentItem(), None)

    def _collect_effects(self) -> None:
        if self._loading:
            return
        out = []
        for it in self._fx_items():
            if it.checkState(0) == Qt.CheckState.Checked:
                eid = it.data(0, Qt.ItemDataRole.UserRole)
                st = self._fx_state[eid]
                entry = {"id": eid, "intensity": st["intensity"]}
                if st["start"] > 0 or st["end"] > 0:
                    entry["start"] = st["start"]
                    entry["end"] = st["end"] if st["end"] > 0 else None
                out.append(entry)
        self.project.effects = out

    def _on_fx_selected(self, item, _prev) -> None:
        eid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not eid:
            self.fx_box.setEnabled(False)
            return
        st = self._fx_state[eid]
        self._loading = True
        self.fx_box.setTitle(f"Einstellungen: {fx.REGISTRY[eid].name}")
        self.fx_int.setValue(int(st["intensity"]))
        self.fx_int_label.setText(str(int(st["intensity"])))
        self.fx_start.setValue(st["start"])
        self.fx_end.setValue(st["end"])
        self._loading = False
        self.fx_box.setEnabled(True)

    def _on_fx_param(self) -> None:
        self.fx_int_label.setText(str(self.fx_int.value()))
        if self._loading:
            return
        item = self.fx_tree.currentItem()
        eid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not eid:
            return
        self._fx_state[eid] = {"intensity": self.fx_int.value(), "start": self.fx_start.value(),
                               "end": self.fx_end.value()}
        self._collect_effects()

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
        idx = self.text_font.findData(t.font)
        self.text_font.setCurrentIndex(idx if idx >= 0 else max(0, self.text_font.count() - 1))
        self._text_color = t.color if t.color.startswith("#") else "#ffffff"
        self._style_color_button()
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
        item = self.text_list.item(row)
        if item:
            item.setText(self._text_title(t))

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
                errors.append(f"{Path(f).name}: {exc}")
                continue
            self.media[f] = info
            it = QListWidgetItem(f"{Path(f).name}   ({fmt_time(info.duration)}, {info.width}×{info.height})")
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
        clip = Clip(path, info.duration, has_audio=info.has_audio, width=info.width, height=info.height)
        self.project.clips.append(clip)
        self._refresh_timeline(select=len(self.project.clips) - 1)

    # ------------------------------------------------------------ Timeline
    def _refresh_timeline(self, select: int | None = None) -> None:
        if select is not None:
            self.sel = select
        self.sel = min(self.sel, len(self.project.clips) - 1)
        self.timeline.set_clips(self.project.clips, self.sel)
        self.dur_label.setText(f"Gesamtlänge: {fmt_time(self.project.duration)}")
        self._load_clip_fields()

    def _select_clip(self, idx: int) -> None:
        self.sel = idx
        self._load_clip_fields()
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
            del self.project.clips[self.sel]
            self._refresh_timeline(select=min(self.sel, len(self.project.clips) - 1))

    def split_clip(self) -> None:
        if not (0 <= self.sel < len(self.project.clips)):
            return
        c = self.project.clips[self.sel]
        t = self.player.position() / 1000.0
        if self._cur_path != c.path or not (c.in_pt + 0.1 < t < c.out_pt - 0.1):
            self.statusBar().showMessage("Zum Teilen: Clip auswählen und im Player an die gewünschte Stelle springen.")
            return
        second = copy.copy(c)
        c.out_pt = t
        second.in_pt = t
        self.project.clips.insert(self.sel + 1, second)
        self._refresh_timeline(select=self.sel)

    # ------------------------------------------------------- Clip-Eigenschaften
    def _load_clip_fields(self) -> None:
        ok = 0 <= self.sel < len(self.project.clips)
        self.clip_tab.setEnabled(ok)
        if not ok:
            self.clip_name.setText("Kein Clip ausgewählt")
            return
        c = self.project.clips[self.sel]
        self._loading = True
        self.clip_name.setText(c.name)
        self.clip_in.setRange(0.0, c.duration)
        self.clip_out.setRange(0.05, c.duration)
        self.clip_in.setValue(c.in_pt)
        self.clip_out.setValue(c.out_pt)
        self.clip_speed.setValue(c.speed)
        self.clip_vol.setValue(int(c.volume * 100))
        self.clip_vol_label.setText(f"{int(c.volume * 100)} %")
        self.clip_mute.setChecked(c.mute)
        self.clip_mute.setEnabled(c.has_audio)
        self.clip_rev.setChecked(c.reverse)
        self._loading = False

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
        self.timeline.set_clips(self.project.clips, self.sel)
        self.dur_label.setText(f"Gesamtlänge: {fmt_time(self.project.duration)}")

    # --------------------------------------------------------------- Player
    def _open_media(self, path: str, seek_ms: int, limit_ms: int | None, autoplay: bool) -> None:
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
        worker.progress.connect(lambda p: dlg.setValue(int(p * 100)))
        dlg.canceled.connect(worker.cancel)

        def finished(err: str):
            dlg.close()
            self._worker = None
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
        return True

    def export_video(self) -> None:
        if not self._check_ready():
            return
        out, _ = QFileDialog.getSaveFileName(self, "Video exportieren", str(Path.home() / "Mein_Video.mp4"), "MP4-Video (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        try:
            cmd, total, tmp = exporter.build_command(self.project, out)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export", str(exc))
            return
        self._tmp_dirs.append(tmp)

        def done(err: str):
            if err:
                QMessageBox.critical(self, "Export fehlgeschlagen", err)
            else:
                self.statusBar().showMessage(f"Export fertig: {out}")
                if QMessageBox.question(self, "Export fertig", f"Gespeichert unter:\n{out}\n\nOrdner öffnen?") == QMessageBox.StandardButton.Yes:
                    self._open_folder(str(Path(out).parent))

        self._run_job(cmd, total, "Video wird exportiert …", done)

    def render_preview(self) -> None:
        if not self._check_ready():
            return
        out = os.path.join(tempfile.mkdtemp(prefix="clipforge_prev_"), "preview.mp4")
        try:
            cmd, total, tmp = exporter.build_command(self.project, out, draft=True, max_seconds=8.0)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Vorschau", str(exc))
            return
        self._tmp_dirs.append(tmp)

        def done(err: str):
            if err:
                QMessageBox.critical(self, "Vorschau fehlgeschlagen", err)
            else:
                self._cur_path = ""
                self._open_media(out, 0, None, autoplay=True)
                self.statusBar().showMessage("Vorschau (halbe Auflösung, erste 8 Sekunden)")

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
        f, _ = QFileDialog.getSaveFileName(self, "Projekt speichern", self._project_file or "Projekt.cforge", "ClipForge-Projekt (*.cforge)")
        if f:
            self.project.save(f)
            self._project_file = f
            self.statusBar().showMessage(f"Gespeichert: {f}")

    def open_project(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Projekt öffnen", "", "ClipForge-Projekt (*.cforge)")
        if not f:
            return
        try:
            self.project = Project.load(f)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Projekt öffnen", f"Datei konnte nicht gelesen werden:\n{exc}")
            return
        self._project_file = f
        missing = [c.name for c in self.project.clips if not os.path.exists(c.path)]
        self._sync_controls_from_project()
        self._refresh_timeline(select=0 if self.project.clips else -1)
        if missing:
            QMessageBox.warning(self, "Projekt", "Diese Dateien fehlen:\n" + "\n".join(missing))

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

    def about(self) -> None:
        QMessageBox.about(self, f"Über {APP_NAME}",
                          f"<b>{APP_NAME}</b> {VERSION}<br>Videoschnitt mit Presets für YouTube, Shorts, TikTok und Reels.<br><br>"
                          "Nutzt FFmpeg (ffmpeg.org) zum Rendern.")

    def closeEvent(self, event):
        try:
            self.player.stop()
        finally:
            for d in self._tmp_dirs:
                shutil.rmtree(d, ignore_errors=True)
        super().closeEvent(event)
