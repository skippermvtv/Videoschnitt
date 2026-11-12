"""Prüft das Hauptfenster mit Attrappen, die Qt-Signale WIRKLICH auslösen (ohne echtes Qt).

Warum: Qt gibt Fehler in Slots nur aus und läuft weiter – und beim Aufbau des Fensters feuern Felder,
wenn man ihnen einen Startwert gibt. Dieser Test findet solche Fehler (z. B. ein Handler, der einen
Regler braucht, den es beim Aufbau noch nicht gibt), ohne dass PySide6 installiert sein muss.
Ersetzt NICHT tests/ui_smoke.py (echtes Qt, läuft auf GitHub).
"""
import sys
import tempfile
import traceback
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.paths import find_binary  # noqa: E402

FFMPEG = find_binary("ffmpeg")      # mitgeliefertes FFmpeg bzw. PATH (auf dem Build-Server liegt es nur in vendor/)

ERRORS: list[str] = []


class Sig:
    def __init__(self, owner):
        self.owner, self.slots = owner, []

    def connect(self, fn, *a, **k):
        self.slots.append(fn)

    def disconnect(self, *a, **k):
        self.slots.clear()

    def emit(self, *args):
        if self.owner._blocked:
            return
        for fn in list(self.slots):
            try:
                try:
                    fn(*args)
                except TypeError as exc:   # Qt reicht zu viele Argumente einfach nicht weiter
                    if "positional argument" in str(exc) or "takes" in str(exc):
                        fn()
                    else:
                        raise
            except Exception:  # noqa: BLE001 - wie Qt: ausgeben, weiterlaufen; der Test wertet am Ende aus
                ERRORS.append(traceback.format_exc())


SIGNALS = ("valueChanged", "currentIndexChanged", "toggled", "textChanged", "clicked", "stateChanged", "itemChanged",
           "currentItemChanged", "itemSelectionChanged", "currentTextChanged", "timeout", "triggered", "sliderMoved",
           "canceled", "finished", "activated", "editingFinished", "itemClicked", "itemDoubleClicked", "currentChanged")


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        v = Stub()
        setattr(cls, name, v)
        return v


class Stub(metaclass=_Meta):
    def __init__(self, *a, **k):
        object.__setattr__(self, "_blocked", False)
        object.__setattr__(self, "_v", 0)
        object.__setattr__(self, "_checked", False)
        object.__setattr__(self, "_idx", -1)
        object.__setattr__(self, "_items", [])
        object.__setattr__(self, "_text", "")
        object.__setattr__(self, "_lo", None)
        object.__setattr__(self, "_hi", None)

    def __call__(self, *a, **k):
        return Stub()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in SIGNALS:
            s = Sig(self)
            object.__setattr__(self, name, s)
            return s
        v = Stub()
        object.__setattr__(self, name, v)
        return v

    def __iter__(self):
        return iter(())

    def __lt__(self, o):
        return False
    __gt__ = __le__ = __ge__ = __lt__

    def __int__(self):
        return int(self._v)

    def __float__(self):
        return float(self._v)

    def __index__(self):
        return int(self._v)

    def __sub__(self, o):
        return 0

    def __add__(self, o):
        return 0

    def __or__(self, o):
        return Stub()
    __ror__ = __or__

    # --- zustandsbehaftete Widget-Methoden
    def blockSignals(self, b):
        old = self._blocked
        object.__setattr__(self, "_blocked", bool(b))
        return old

    def signalsBlocked(self):
        return self._blocked

    def setRange(self, lo, hi):
        object.__setattr__(self, "_lo", lo)
        object.__setattr__(self, "_hi", hi)
        if self._lo is not None and isinstance(self._v, (int, float)) and self._v < lo:
            self.setValue(lo)

    def setValue(self, v):
        if isinstance(v, (int, float)) and self._lo is not None:
            v = min(max(v, self._lo), self._hi)
        if v != self._v:
            object.__setattr__(self, "_v", v)
            self.valueChanged.emit(v)

    def value(self):
        return self._v

    def setChecked(self, b):
        b = bool(b)
        if b != self._checked:
            object.__setattr__(self, "_checked", b)
            self.toggled.emit(b)

    def isChecked(self):
        return self._checked

    def addItem(self, text, data=None):
        self._items.append((text, data))
        if len(self._items) == 1:
            object.__setattr__(self, "_idx", 0)
            self.currentIndexChanged.emit(0)

    def clear(self):
        had = bool(self._items)
        self._items.clear()
        object.__setattr__(self, "_idx", -1)
        if had:
            self.currentIndexChanged.emit(-1)

    def count(self):
        return len(self._items)

    def findData(self, d):
        for i, (_, x) in enumerate(self._items):
            if x == d:
                return i
        return -1

    def currentData(self, *a):
        return self._items[self._idx][1] if 0 <= self._idx < len(self._items) else None

    def itemData(self, i, *a):
        return self._items[i][1] if 0 <= i < len(self._items) else None

    def currentIndex(self):
        return self._idx

    def setCurrentIndex(self, i):
        if i != self._idx:
            object.__setattr__(self, "_idx", i)
            self.currentIndexChanged.emit(i)

    def setText(self, t):
        object.__setattr__(self, "_text", str(t))
        self.textChanged.emit(str(t))

    def text(self):
        return self._text


def Signal(*a, **k):
    return Stub()


def make(name, attrs=()):
    m = types.ModuleType(name)
    m.__getattr__ = lambda n: Stub if n[0].isupper() else (_ for _ in ()).throw(AttributeError(n))
    for k, v in attrs:
        setattr(m, k, v)
    sys.modules[name] = m
    return m


make("PySide6")
make("PySide6.QtCore", [("Signal", Signal)])
make("PySide6.QtGui")
make("PySide6.QtWidgets")
make("PySide6.QtMultimedia")
make("PySide6.QtMultimediaWidgets")
import PySide6.QtCore as C  # noqa: E402


class QThread(Stub):
    pass


C.QThread = QThread

from app.ui import main_window as mw  # noqa: E402
from app.ui import timeline as tl  # noqa: E402


def _strict(allowed):
    """Eigene Fenster-Klassen dürfen nur echte Qt-Methoden 'erfinden'; ein fehlendes eigenes Attribut ist ein Fehler."""
    def getattr_(self, name):
        if name in allowed:
            v = Stub()
            object.__setattr__(self, name, v)
            return v
        raise AttributeError(f"'{type(self).__name__}' hat kein Attribut '{name}'")
    return getattr_


# Qt-eigene Methoden, die MainWindow/Timeline aufrufen (aus der statischen Attribut-Prüfung)
mw.MainWindow.__getattr__ = _strict({"setWindowTitle", "setWindowIcon", "resize", "setAcceptDrops", "setCentralWidget", "font",
                                     "statusBar", "addToolBar", "menuBar", "addAction", "close", "show", "grab", "update"})
tl.Timeline.__getattr__ = _strict({"setMinimumHeight", "setMouseTracking", "update", "width", "rect", "font", "height",
                                   "setCursor", "setFocusPolicy", "setSizePolicy", "setToolTip", "addAction", "setFocus", "setAcceptDrops", "setContextMenuPolicy", "setMaximumHeight"})


def no_errors(where: str):
    if ERRORS:
        print(f"FEHLER in einem Slot ({where}):\n" + ERRORS[0])
        print(f"({len(ERRORS)} Fehler insgesamt)")
        sys.exit(1)


win = mw.MainWindow()
no_errors("Fenster aufbauen")
print("OK  Fenster aufgebaut, keine Fehler in Slots")

# Projekt-Zustand in die Felder laden und alle Auswahl-Wechsel durchspielen
tmp = Path(tempfile.mkdtemp())
import subprocess  # noqa: E402

vid = tmp / "t.mp4"
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
                "-f", "lavfi", "-i", "sine=duration=4", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(vid)], check=True)
wav = tmp / "m.wav"
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=500:duration=2", str(wav)], check=True)
png = tmp / "i.png"
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=200x200:d=1", "-frames:v", "1", str(png)], check=True)

win.import_files([str(vid)])
win._add_to_timeline(str(vid))
no_errors("Clips importieren")
for i in (0, 1, 0):
    win._select_clip(i)
    no_errors(f"Clip {i} wählen")
win.detach_selected_audio()
no_errors("Ton trennen")
win.add_audio_files([str(wav)], track=2)
no_errors("Musik hinzufügen")
for i in (0, 1, 0):
    win._select_audio(i)
    no_errors(f"Audioblock {i} wählen")
win.aud_vol.setValue(50)
win.aud_speed.setValue(1.5)
win.aud_loop.setChecked(True)
win.aud_fin.setValue(0.5)
no_errors("Audiofelder ändern")
assert abs(win.project.audio_clips[0].volume - 0.5) < 1e-6, "Lautstärke wurde nicht übernommen"
win.mix_duck.setChecked(True)
win.mix_duck_amount.setValue(30)
win.mix_norm.setChecked(True)
no_errors("Mischpult")
win.clip_vol.setValue(80)
win.clip_speed.setValue(2.0)
win.clip_trans_dur.setValue(0.5)
no_errors("Clipfelder ändern")
win.add_text()
no_errors("Text hinzufügen")
win.text_anim_dur.setValue(0.8)
win.sub_size.setValue(7.0)
no_errors("Text-/Untertitelstil")
try:
    win.add_overlay_files([str(png)])
except AttributeError:
    win.add_overlay([str(png)]) if hasattr(win, "add_overlay") else None
no_errors("Bild-in-Bild hinzufügen")
win.cmb_format.setCurrentIndex(min(1, max(0, win.cmb_format.count() - 1)))
win.chk_hw.setChecked(True)
win.cmb_prev_q.setCurrentIndex(0)
no_errors("Format/Leistung")
win.undo()
win.redo()
no_errors("Rückgängig/Wiederholen")
print("OK  Felder, Auswahl, Mischpult, Text, Bild-in-Bild, Format")

# --- weitere Reiter: Bewegung (Keyframes), Untertitel, Bildkorrektur, Looks, Übergänge, Text
win._select_clip(0)
win.add_keyframe()
win.add_keyframe()
no_errors("Keyframes anlegen")
win._on_kf_selected(0)
win.kf_ease.setChecked(False)
for k, f in list(win.kf_fields.items())[:3]:
    f.setValue(110.0 if k == "zoom" else 5.0)
no_errors("Keyframe-Felder")
win.remove_keyframe()
win.clear_motion()
no_errors("Keyframes löschen")
win._rotate_clip(1)
win.reset_transform()
no_errors("Drehen/Zurücksetzen")
win.add_subtitle()
win.add_subtitle()
no_errors("Untertitel anlegen")
win._on_sub_selected(0)
win.sub_size.setValue(8.0)
win.sub_pos.setCurrentIndex(0)
win.sub_anim.setCurrentIndex(min(1, max(0, win.sub_anim.count() - 1)))
no_errors("Untertitelstil")
win.remove_subtitle()
win.clear_subtitles()
no_errors("Untertitel löschen")
for key, sl in list(win._grade_sliders.items())[:4]:
    sl.setValue(15)
no_errors("Bildkorrektur-Regler")
win.reset_grade()
win.apply_grade_to_all()
no_errors("Bildkorrektur zurücksetzen/auf alle")
# 1.3: Farbräder, Kurven, LUT (die Widget-Signale sind hier Attrappen → Handler direkt aufrufen)
win._select_clip(0)
c0 = win.project.clips[0]
for zone in ("lift", "mid", "gain"):
    win._on_wheel(zone, 40, -20, -20)
    assert c0.grade.get(f"{zone}_r") == 40.0, c0.grade
win._on_wheel("mid", 0, 0, 0)
assert "mid_r" not in c0.grade
win.curve_editor.set_curves({"m": [[0, 0], [0.5, 0.7], [1, 1]]})
win._on_curves_changed()
assert c0.grade["curves"]["m"][1] == [0.5, 0.7], c0.grade
win.curve_editor.set_curves({})
win._on_curves_changed()
assert "curves" not in c0.grade
win._on_curve_channel(0)
win.reset_curve()
cube = tmp / "t.cube"
with open(cube, "w", encoding="utf-8") as fh:
    fh.write("LUT_3D_SIZE 2\n" + "\n".join(f"{r} {g} {b}" for b in (0, 1) for g in (0, 1) for r in (0, 1)) + "\n")
import os as _os  # noqa: E402
_os.environ["APPDATA"] = str(tmp / "appdata")
assert win.set_lut(str(cube)) and c0.grade["lut"].endswith(".cube") and _os.path.exists(c0.grade["lut"])
win._on_lut_mix(40)
assert c0.grade["lut_mix"] == 40.0
win._on_lut_mix(100)
assert "lut_mix" not in c0.grade
win._load_grade_fields()
win.clear_lut()
assert "lut" not in c0.grade
win.reset_grade()
no_errors("Farbräder, Kurven, LUT")
print("   Overlays vorhanden:", len(win.project.overlays))
if win.project.overlays:
    win._select_overlay(0)
    win._on_key_toggle(True)
    assert win.project.overlays[0].key_color == "#00ff00", win.project.overlays[0].key_color
    win._set_key_color("#0000FF")
    assert win.project.overlays[0].key_color == "#0000ff"
    win._on_overlay_field()
    win._overlay_fullscreen()
    assert win.project.overlays[0].size_pct == 100.0
    win._on_key_toggle(False)
    assert win.project.overlays[0].key_color == ""
    win._load_overlay_fields()
    no_errors("Chroma-Key")
print("OK  1.3: Farbräder, Kurven, LUT, Chroma-Key")
win.cmb_look.setCurrentIndex(min(1, max(0, win.cmb_look.count() - 1)))
no_errors("Look wählen")
win.apply_transition_to_all()
win.remove_text()
no_errors("Übergang auf alle, Text entfernen")
win.relink_missing = getattr(win, "relink_missing", None)
win.autosave_now()
win.restore_autosave()
no_errors("Autosave/Wiederherstellen")
win.delete_selected()
win.undo()
no_errors("Löschen/Rückgängig")
win.add_effect_block("glitch", 1.0)
win.fx_int.setValue(40)
win.fx_start.setValue(0.5)
win.fx_end.setValue(2.5)
no_errors("Effekt-Block ändern")
assert win.project.fx_span(win.fsel) == (0.5, 2.5) and win.project.effects[win.fsel]["intensity"] == 40, win.project.effects
win._select_fx(0)
win.cmb_look.setCurrentIndex(min(1, max(0, win.cmb_look.count() - 1)))
win._on_look_chosen(0)
no_errors("Look ersetzt alle Blöcke")
win.add_effect_block("vhs", 2.0)
win.remove_effect_block()
no_errors("Effekt-Block löschen")
print("OK  Bewegung, Untertitel, Bildkorrektur, Look, Übergang, Autosave, Effekt-Spur")

# --- Live-Vorschau (1.4): Hintergrundauftrag durch eine synchrone Attrappe ersetzen, echtes FFmpeg rechnet das Fenster
from app.core import exporter as _exp  # noqa: E402
from app.core import preview as _prev  # noqa: E402


class FakeWorker:
    jobs: list = []

    def __init__(self, cmd, total, parent=None):
        self.cmd, self.total, self._cancel, self.slots = cmd, total, False, []
        self.done = types.SimpleNamespace(connect=self.slots.append)
        self.progress = types.SimpleNamespace(connect=lambda *_a: None)
        FakeWorker.jobs.append(self)

    def cancel(self):
        self._cancel = True

    def start(self):
        try:
            _exp.run(self.cmd, self.total, None, lambda: self._cancel)
            err = ""
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
        for fn in list(self.slots):
            fn(err)

    def wait(self, *_a):
        return True


mw.ExportWorker = FakeWorker
for f in _prev.cache_dir().glob("*.mp4"):
    f.unlink()
win.project.effects = []
win._select_clip(0)
win.timeline.set_playhead(1.0)
state0 = win.project.to_json()
win._live_request()
no_errors("Live-Vorschau rechnen")
assert len(FakeWorker.jobs) == 1 and win._live_path.endswith(".mp4") and Path(win._live_path).stat().st_size > 1000, win._live_path
assert abs(win._live_start_t - 1.0) < 0.01 and win._live_len > 0.5 and win._live_state == state0
assert win._cur_path == win._live_path and win._preview_path == win._live_path and win._preview_start == win._live_start_t
assert win._live_valid_for(1.5) and not win._live_valid_for(0.2) and not win._live_valid_for(win._live_start_t + win._live_len)
print("OK  Live-Vorschau: Fenster gerechnet, im Player, gültig nur im Abschnitt")
n_jobs = len(FakeWorker.jobs)
win._live_request()                                   # gleicher Stand, gleiche Stelle → aus dem Zwischenspeicher
assert len(FakeWorker.jobs) == n_jobs, "unveränderter Stand darf nicht neu gerechnet werden"
win.add_effect_block("bw", 1.0)                       # Änderung → neuer Stand → neu rechnen
assert not win._live_valid_for(1.5), "nach einer Änderung ist die alte Vorschau ungültig"
old = win._live_path
win._live_request()
no_errors("Live-Vorschau nach Änderung")
assert len(FakeWorker.jobs) == n_jobs + 1 and win._live_path != old and win._live_valid_for(1.5)
win._seek_project(2.0)                                # innerhalb des Abschnitts: bleibt in der Vorschau
assert win._cur_path == win._live_path
win._live_timer.stop()
win._seek_project(0.0)                                # außerhalb: Original, Live-Anfrage wird eingeplant
assert win._cur_path != win._live_path
no_errors("Live-Vorschau: Suchen")
win.set_live(False)
win._live_changed()
assert not win._live_timer.isActive() if hasattr(win._live_timer, "isActive") and isinstance(win._live_timer.isActive(), bool) else True
n_jobs = len(FakeWorker.jobs)
win._live_request()
assert len(FakeWorker.jobs) == n_jobs, "ausgeschaltet darf nichts gerechnet werden"
win.set_live(True)
# Fehlerfall: kaputter Auftrag zeigt eine Meldung, stürzt nicht ab
FakeWorker.start = lambda self: [fn("FFmpeg-Fehler: test") for fn in self.slots]
win.project.effects = []
win.timeline.set_playhead(1.7)
win._live_request()
assert "fehlgeschlagen" in win.live_label.text() or win.live_label.text() == ""
no_errors("Live-Vorschau: Fehlerfall")
print("OK  Live-Vorschau: Zwischenspeicher, Änderung, Suchen, Ausschalten, Fehlerfall")
# 1.4: neue Oberfläche – Medienraster, Zeitcode, Suchleiste, Zoom
win._on_thumb(next(iter(win.media)), "", "Fehler")                  # Fehler beim Vorschaubild: still ignorieren
win._on_thumb("gibt-es-nicht.mp4", "x.png", "")
win._filter_media("abc")
win._filter_media("")
win._update_duration()
win._show_time(0.5)
win._on_seek_moved(500)
assert abs(win.timeline.playhead - 0.5) < 1e-6
win._on_zoom_slider(40)
win._sync_zoom_slider()
win._on_play_state(None)
no_errors("1.4: Oberfläche")
print("OK  1.4: Medienraster, Zeitcode, Suchleiste, Zoom")
# 1.4: Masken-Effekt: Felder schreiben in den Block, Export-Befehl enthält die Maske
win.project.effects = []
win.add_effect_block("mask_blur", 0.0)
win._on_mask_param()
m = win.project.effects[win.fsel].get("mask")
assert isinstance(m, dict) and set(m) >= {"shape", "x", "y", "w", "h", "feather", "invert", "track"}, m
win.project.effects[win.fsel]["mask"]["track"] = [[0.0, 20.0, 30.0], [2.0, 60.0, 50.0]]
win._on_mask_param()
assert win.project.effects[win.fsel]["mask"]["track"] == [[0.0, 20.0, 30.0], [2.0, 60.0, 50.0]], "Pfad darf beim Ändern der Felder nicht verloren gehen"
from app.core import exporter as _ex
_cmd, _tot, _t = _ex.build_command(win.project, "x.mp4", draft=True)
assert "geq" in " ".join(_cmd)
win.project.effects = []
win.fsel = -1
no_errors("1.4: Maske")
print("OK  1.4: Maskenfelder")
# 1.4.1: Tracking-Ergebnis übernehmen, Fehlerfall, Pfad löschen
from app.core import tracker as _tr
win.add_effect_block("mask_blur", 0.0)
_e = win.project.effects[win.fsel]
win._track_target = _e
win._track_done(_tr.TrackResult(points=[[0.0, 20.0, 30.0], [1.0, 60.0, 50.0]], frames=12, lost=0, seconds=1.0), "")
_m = win.project.effects[win.fsel]["mask"]
assert _m["track"] == [[0.0, 20.0, 30.0], [1.0, 60.0, 50.0]] and (_m["x"], _m["y"]) == (20.0, 30.0), _m
win._track_target = _e
win._track_done(None, "Der Block ist zu kurz zum Verfolgen.")
assert win.project.effects[win.fsel]["mask"]["track"], "Fehler darf den Pfad nicht löschen"
win._track_target = {"id": "fremd"}
win._track_done(_tr.TrackResult(points=[[0.0, 1.0, 1.0]], frames=1, lost=0, seconds=0.1), "")
assert win.project.effects[win.fsel]["mask"]["track"][0][1] == 20.0, "fremder Block darf nichts ändern"
win._track_clear()
assert win.project.effects[win.fsel]["mask"]["track"] == []
win.project.effects = []
win.fsel = -1
no_errors("1.4.1: Tracking")
print("OK  1.4.1: Tracking-Übernahme")
# 1.4.1: Stabilisierung – Analyse wird vor Live-Vorschau/Export eingeplant, Fehler → Notlösung ohne Endlosschleife
from app.core import stabilize as _st
if _st.available():
    _c = win.project.clips[0]
    _c.stabilize = 50
    _ran = []
    assert win._stab_wait(lambda: _ran.append(1)) is True and win._stab_worker is not None, "Analyse muss starten"
    assert win._stab_wait(lambda: _ran.append(2)) is True, "zweite Anfrage reiht sich ein"
    win._stab_done("")
    assert _ran == [1, 2] and win._stab_worker is None, _ran
    win._stab_fail_state = ""
    win._stab_wait(None)
    win._stab_done("FFmpeg-Fehler: test")
    assert win._stab_wait(None) is False, "nach Fehler keine Endlosschleife"
    _c.stabilize = 0
    win._stab_fail_state = ""
    assert win._stab_wait(None) is False, "ohne Stabilisierung nichts zu tun"
    no_errors("1.4.1: Stabilisierung")
    print("OK  1.4.1: Stabilisierung (Ablauf)")
# 1.4.1: Medien aus dem Raster einfügen, Stumm-Schalter im Spurkopf
_vid = next(iter(win.media))
_n = len(win.project.clips)
win._on_media_dropped([_vid, _vid], 0)
assert len(win.project.clips) == _n + 2 and win.sel == 1, (len(win.project.clips), win.sel)
win._on_media_dropped([_vid], 999)
assert len(win.project.clips) == _n + 3 and win.sel == _n + 2
win._on_lane_mute(2)
no_errors("1.4.1: Medien ablegen / Spurkopf")
print("OK  1.4.1: Medien ablegen, Spurkopf")
# 1.4.2: Titel-Vorlagen und Übergänge
_nt = len(win.project.texts)
win.add_title("lower_third", 1.5)
assert len(win.project.texts) == _nt + 1 and win.project.texts[-1].start == 1.5 and win.project.texts[-1].box, win.project.texts[-1]
win.add_title("metal", 3.0)
assert "FateMetal" in win.project.texts[-1].font and win.project.texts[-1].start == 3.0
win.add_title("gibt-es-nicht")
assert len(win.project.texts) == _nt + 2, "unbekannte Vorlage darf nichts anlegen"
win._on_title_dropped("quote", 2.0)
assert len(win.project.texts) == _nt + 3 and win.project.texts[-1].start == 2.0
win.project.texts = win.project.texts[:_nt]
win._on_media_dropped([_vid, _vid], 0)
_cl = win.project.clips
assert len(_cl) >= 3
win.trans_dur.setValue(0.5)
win.apply_transition("fade", 0)
assert _cl[0].transition == "fade" and abs(_cl[0].transition_dur - 0.5) < 1e-9, (_cl[0].transition, _cl[0].transition_dur)
win.apply_transition("wipeleft", None, all_clips=True)
assert all(c.transition == "wipeleft" for c in _cl[:-1]) and _cl[-1].transition == "", [c.transition for c in _cl]
win.apply_transition("", 1)
assert _cl[1].transition == "" and _cl[0].transition == "wipeleft"
win.apply_transition("fade", len(_cl) - 1)
assert _cl[-1].transition == "", "der letzte Clip hat keinen Übergang"
win._on_transition_dropped("slideleft", 1)
assert _cl[1].transition == "slideleft"
win._on_trans_thumb("fade", "/gibt/es/nicht.png", "")
win._on_trans_thumb("fade", "", "Fehler")
for _c in _cl:
    _c.transition = ""
no_errors("1.4.2: Titel, Übergänge")
print("OK  1.4.2: Titel-Vorlagen, Übergänge")
# 1.4.2: Ton verbessern (Regler → Clip / Audioblock)
win._select_clip(0)
win.clip_dn.setValue(40)
win.clip_vc.setValue(25)
win._on_clip_field()
assert win.project.clips[0].denoise == 40 and win.project.clips[0].voice == 25, (win.project.clips[0].denoise, win.project.clips[0].voice)
win.project.clips[0].denoise = win.project.clips[0].voice = 0
from app.core.project import AudioClip  # noqa: E402
_ac = AudioClip(_vid, 5.0, track=1)
win.project.audio_clips = [_ac]
win._select_audio(0)
win.aud_dn.setValue(60)
win.aud_vc.setValue(30)
win._on_audio_field()
assert _ac.denoise == 60 and _ac.voice == 30, (_ac.denoise, _ac.voice)
win.project.audio_clips = []
no_errors("1.4.2: Ton verbessern")
print("OK  1.4.2: Ton verbessern")
# 1.4.2: Split Screen
from app.core.project import OverlayClip  # noqa: E402
win.project.overlays = [OverlayClip(_vid, 5.0, start=0.0), OverlayClip(_vid, 5.0, start=1.0)]
win.osel = 0
win.split_layout.setCurrentIndex(0)
assert win.apply_split("4") == [], "vier Felder mit zwei Blöcken"
assert not any(o.cell for o in win.project.overlays)
assert "braucht 4" in win.split_info.text() or "4" in win.split_info.text(), win.split_info.text()
assert win.apply_split("2h") == [0, 1] and win.project.overlays[0].cell == [0, 0, 50, 100] and win.project.overlays[1].cell == [50, 0, 50, 100]
assert win.osel == 0
win.clear_split()
assert not any(o.cell for o in win.project.overlays)
win.clear_split()
assert "kein Split" in win.split_info.text()
win.project.overlays = []
assert win.split_from_media("2h") == [], "ohne markierte Medien"
no_errors("1.4.2: Split Screen")
print("OK  1.4.2: Split Screen")
# 1.4.2: Geschwindigkeitskurve
win.project.overlays = []
win.project.clips = win.project.clips[:1]
win._select_clip(0)
_n0 = len(win.project.clips)
win.ramp_text.setText("0:1, 50:0.25, 100:1")
win._on_ramp_text()
assert "Länge" in win.ramp_info.text(), win.ramp_info.text()
_used = win.apply_speed_ramp()
assert len(_used) >= 5 and len(win.project.clips) == _n0 - 1 + len(_used), (len(_used), len(win.project.clips))
win.ramp_text.setText("0:1, 200:5")
assert win.apply_speed_ramp() == [] and "200" in win.ramp_info.text(), win.ramp_info.text()
win.ramp_text.setText("abc")
assert win.apply_speed_ramp() == []
win.sel = -1
win.ramp_text.setText("0:1, 100:2")
assert win.apply_speed_ramp() == []
win.ramp_text.setText("")
win._on_ramp_curve([[0, 1], [40, 0.3], [100, 1.5]])
assert win.ramp_text.text() == "0:1, 40:0.3, 100:1.5", win.ramp_text.text()
win.sel = 0
win._on_ramp_text()
assert "Länge" in win.ramp_info.text(), win.ramp_info.text()
no_errors("1.4.2: Geschwindigkeitskurve")
print("OK  1.4.2: Geschwindigkeitskurve")
# 1.4.3: Ton von Bild-in-Bild, Ziel-Lautheit
win.project.overlays = [OverlayClip(_vid, 5.0, start=0.0)]
win.osel = 0
win.ov_sound.setChecked(True)
win.ov_volume.setValue(60.0)
win._on_overlay_field()
assert win.project.overlays[0].sound is True and win.project.overlays[0].volume == 60.0, (win.project.overlays[0].sound, win.project.overlays[0].volume)
win.project.overlays = []
win.mix_norm.setChecked(True)
win.mix_lufs.setCurrentIndex(2)
win._on_mix_field()
assert win.project.normalize is True and win.project.lufs_target == -23.0, win.project.lufs_target
win.project.normalize = False
win.project.lufs_target = -14.0
no_errors("1.4.3: Ton Bild-in-Bild, Lautheit")
print("OK  1.4.3: Ton Bild-in-Bild, Ziel-Lautheit")
# 1.4.3: Split mit Linie, Hauptvideo, Ausschnitt
win.project.overlays = [OverlayClip(_vid, 5.0, start=0.0), OverlayClip(_vid, 5.0, start=1.0)]
win.osel = 0
win.split_gap.setValue(4.0)
win.split_line.setCurrentIndex(1)
win.split_main.setCurrentIndex(1)
assert win.apply_split("3l") == [0, 1], "mit Hauptvideo reichen zwei Blöcke für drei Felder"
_o = win.project.overlays
assert _o[0].cell_gap == 4.0 and _o[0].cell_line == "#ffffff" and _o[0].main_cell == [0, 0, 50, 100] and _o[0].cell == [50, 0, 50, 50], (_o[0].cell_gap, _o[0].cell_line, _o[0].main_cell, _o[0].cell)
win.osel = 1
win.ov_cz.setValue(150.0)
win.ov_cdx.setValue(-30.0)
win._on_overlay_field()
assert _o[1].cell_zoom == 150.0 and _o[1].cell_dx == -30.0
win.clear_split()
assert not any(o.cell or o.main_cell for o in win.project.overlays) and _o[1].cell_zoom == 100.0
win.project.overlays = []
win.split_main.setCurrentIndex(0)
win.split_gap.setValue(0.0)
no_errors("1.4.3: Split Zusätze")
print("OK  1.4.3: Split Linie/Hauptvideo/Ausschnitt")
# 1.4.5: Kurve nachträglich ändern
from app.core import speedramp as _rm  # noqa: E402
win._select_clip(0)
win.remove_speed_ramp()                          # falls Clip 0 aus einem früheren Abschnitt schon eine Kurve trägt
_n0 = len(win.project.clips)
win.ramp_text.setText("0:1, 50:0.3, 100:1")
_u1 = win.apply_speed_ramp()
assert _u1 and _rm.group_of(win.project, win.sel) is not None
win._select_clip(_u1[2])
win._show_ramp_group()
win.ramp_text.setText("0:2, 100:0.5")
_u2 = win.apply_speed_ramp()
assert _u2 and _rm.curve_of(win.project, _u2[0]) == [[0.0, 2.0], [100.0, 0.5]]
_ok = win.remove_speed_ramp()
assert _ok is True and len(win.project.clips) == _n0, (_ok, len(win.project.clips), _n0, win.sel, _u2[:3])
assert win.remove_speed_ramp() is False
no_errors("1.4.5: Kurve nachträglich ändern")
print("OK  1.4.5: Kurve nachträglich ändern")
# 1.4.5: eigene Tempokurven
from app.core import settings as _stm  # noqa: E402
_stm.save({"my_ramps": []})
win.ramp_text.setText("0:1, 50:0.3, 100:1")
assert win.save_my_ramp("Test Kurve") is True
assert [c["name"] for c in _stm.load()["my_ramps"]] == ["Test Kurve"]
win.ramp_text.setText("kaputt")
assert win.save_my_ramp("Andere") is False
assert [c["name"] for c in _stm.load()["my_ramps"]] == ["Test Kurve"]
win.ramp_text.setText("0:1, 100:1")
assert win.save_my_ramp("   ") is False
_stm.save({"my_ramps": []})
no_errors("1.4.5: Eigene Kurven")
print("OK  1.4.5: Eigene Kurven")
# 1.4.5: Lautheit nach dem Export
win._last_loudness = None
assert win._loudness_text() == ""
win._last_loudness = -13.24
win.project.normalize, win.project.lufs_target = True, -14.0
assert win._loudness_text() == "Lautheit: −13,2 LUFS (Ziel −14,0)", win._loudness_text()
win.project.normalize = False
assert win._loudness_text() == "Lautheit: −13,2 LUFS", win._loudness_text()
win._last_loudness = None
no_errors("1.4.5: Lautheit nach Export")
print("OK  1.4.5: Lautheit nach Export")
# 1.4.4: Chroma-Key auf dem Hauptvideo
win.project.overlays = []
win.project.clips = win.project.clips[:1]
win._select_clip(0)
_ck = win.project.clips[0]
assert _ck.key_color == "" and _ck.key_bg == ""
win._on_ck_toggle(True)
assert _ck.key_color == "#00ff00", _ck.key_color
win._set_ck_color("#0000FF")
assert _ck.key_color == "#0000ff"
_ck.key_bg = "/x/hintergrund.png"
win._show_ck(_ck)
win._clear_ck_bg()
assert _ck.key_bg == ""
_png = win._key_preview_file()
assert Path(_png).is_file() and Path(_png).stat().st_size > 100, _png
win._on_ck_toggle(False)
assert _ck.key_color == ""
win._load_clip_fields() if hasattr(win, "_load_clip_fields") else None
no_errors("1.4.4: Chroma-Key Hauptvideo")
print("OK  1.4.4: Chroma-Key Hauptvideo")
# 1.4.4: Was-ist-neu-Fenster (Logik; das echte Fenster prüft ui_smoke)
from app.core import settings as _stw  # noqa: E402
_stw.save({"last_version": "1.0.0", "whatsnew_off": False})
assert win._check_whats_new() is True
assert _stw.load()["last_version"] != "1.0.0"
_stw.save({"last_version": "99.0.0"})
assert win._check_whats_new() is False
no_errors("1.4.4: Was ist neu")
print("OK  1.4.4: Was ist neu")
# 1.4.7: Bild-in-Bild Keyframes, Vorlagen, Rückwärts
from app.core import overlaykeys as _ok  # noqa: E402
win.project.overlays = [OverlayClip(_vid, 5.0, start=2.0, x_pct=70.0, y_pct=30.0, size_pct=30.0)]
win.osel = 0
win._load_overlay_fields()
_o = win.project.overlays[0]
assert not _ok.active(_o)
win.timeline.set_playhead(3.0)                                    # 1 s im Block (5 s lang) = 20 %
win.add_overlay_key()
assert _ok.active(_o) and len(_o.keys) == 3 and any(abs(k["t"] - 0.2) < 1e-6 for k in _o.keys), _o.keys
win._on_overlay_key_requested(0, 0.6)
assert len(_o.keys) == 4 and any(abs(k["t"] - 0.6) < 1e-6 for k in _o.keys)
win._on_overlay_key_requested(1, 0.9)                            # anderer Block: nichts
assert len(_o.keys) == 4
win.ov_kf_pick.setCurrentIndex(1)
win.ov_kf_x.setValue(10.0)
win._on_ovk_field()
assert any(abs(k["x"] - 10.0) < 1e-6 for k in _o.keys), _o.keys
win._goto_overlay_key(1)                                          # springt zum nächsten Punkt hinter dem Abspielkopf
win.remove_overlay_key()
assert len(_o.keys) == 3, _o.keys
win.clear_overlay_keys()
assert _o.keys == []
win.ov_kf_preset.setCurrentIndex(win.ov_kf_preset.findData("in_left"))
win._apply_ovk_preset()
assert _ok.active(_o) and _o.keys[0]["x"] < 0, _o.keys
win._on_ovk_ease(False)
assert _o.anim_ease is False
win.ov_reverse.setChecked(True)
win._on_overlay_field()
assert _o.reverse is True
_o.cell = [0, 0, 50, 50]
win.add_overlay_key()
assert not _ok.active(_o), "im Split-Feld gibt es keine Keyframes"
win.project.overlays = []
win.osel = -1
no_errors("1.4.7: Bild-in-Bild Keyframes")
print("OK  1.4.7: Bild-in-Bild Keyframes")
# 1.4.8: Karaoke-Untertitel und Untertitel-Vorschau
win.sub_karaoke.setChecked(True)
win._on_sub_style()
assert win.project.sub_style.karaoke is True and win.project.sub_style.karaoke_mode == "stay"
win.sub_kar_mode.setCurrentIndex(win.sub_kar_mode.findData("active"))
win._on_sub_style()
assert win.project.sub_style.karaoke_mode == "active"
win._sub_kar_color = "#00ff88"
win._on_sub_style()
assert win.project.sub_style.karaoke_color == "#00ff88"
win.project.sub_style.karaoke, win.project.sub_style.karaoke_mode = False, "stay"
win._load_sub_style()
assert not win.sub_karaoke.isChecked()
no_errors("1.4.8: Karaoke")
print("OK  1.4.8: Karaoke-Untertitel")
# 1.4.8: Tastenkürzel für den Schnitt
_calls = []
win._seek_project = lambda t: _calls.append(("seek", round(t, 4)))
win.split_clip = lambda: _calls.append(("split",))
win.delete_selected = lambda: _calls.append(("delete",))
win.toggle_play = lambda: _calls.append(("play",))
_dur = win.project.duration
assert win.project.clips and _dur > 3.0
win.timeline.set_playhead(2.0)
_fr = win._frame_step()
assert 1 / 61 < _fr < 1 / 23, _fr
assert win.edit_key("right") and _calls[-1] == ("seek", round(2.0 + _fr, 4)), _calls
assert win.edit_key("left", shift=True) and _calls[-1] == ("seek", 1.0)
win.timeline.set_playhead(0.0)
win.edit_key("left")
assert _calls[-1] == ("seek", 0.0), "nicht vor den Anfang"
win.timeline.set_playhead(_dur)
win.edit_key("right", shift=True)
assert _calls[-1][1] <= round(_dur - 0.01, 4), _calls[-1]
win.edit_key("home")
assert _calls[-1] == ("seek", 0.0)
win.edit_key("end")
assert abs(_calls[-1][1] - (_dur - 0.05)) < 1e-3
assert win.edit_key("s") and _calls[-1] == ("split",)
assert win.edit_key("delete") and _calls[-1] == ("delete",)
assert win.edit_key("space") and _calls[-1] == ("play",)
assert win.edit_key("x") is False
_saved, win.project.clips = win.project.clips, []
assert win.edit_key("s") is False, "ohne Clips nichts"
win.project.clips = _saved
for _n in ("_seek_project", "split_clip", "delete_selected", "toggle_play"):
    del win.__dict__[_n]
no_errors("1.4.8: Tastenkürzel")
print("OK  1.4.8: Tastenkürzel")
# 1.4.9: Stille entfernen (Anwenden über das Hauptfenster)
_n0 = len(win.project.clips)
win.sel = 0
_c0 = win.project.clips[0]
_c0.in_pt, _c0.out_pt = 0.0, min(_c0.duration, 3.0)
_used = win.apply_silence_cuts([(1.0, 1.5)])
assert _used == [0, 1] and len(win.project.clips) == _n0 + 1, (_used, len(win.project.clips))
win.project.clips[0].ramp_id = "x"
assert win.apply_silence_cuts([(0.2, 0.4)]) == [], "Clip mit Tempokurve wird abgelehnt (Meldung statt Absturz)"
win.project.clips[0].ramp_id = ""
no_errors("1.4.9: Stille entfernen")
print("OK  1.4.9: Stille entfernen")
# 1.4.9: Szenenerkennung (Anwenden über das Hauptfenster)
_m0 = len(win.project.clips)
win.sel = 0
_d0 = win.project.clips[0]
_d0.in_pt, _d0.out_pt = 0.0, min(_d0.duration, 3.0)
_used2 = win.apply_scene_cuts([1.0, 2.0])
assert _used2 == [0, 1, 2] and len(win.project.clips) == _m0 + 2, (_used2, len(win.project.clips))
win.project.clips[0].reverse = True
assert win.apply_scene_cuts([0.3]) == [], "rückwärts laufender Clip wird abgelehnt (Meldung statt Absturz)"
win.project.clips[0].reverse = False
no_errors("1.4.9: Szenenerkennung")
print("OK  1.4.9: Szenenerkennung")
# 1.4.9: Wasserzeichen
win.set_watermark("/tmp/logo.png")
assert win.project.watermark == "/tmp/logo.png"
win.clear_watermark()
assert win.project.watermark == ""
no_errors("1.4.9: Wasserzeichen")
print("OK  1.4.9: Wasserzeichen")
# 1.4.9: Duplizieren (Strg+D) – Reihenfolge wie beim Löschen: Effekt, Bild-in-Bild, Audio, sonst Clip
win.fsel = win.osel = win.asel = -1
_k0 = len(win.project.clips)
win.sel = 0
win.duplicate_selected()
assert len(win.project.clips) == _k0 + 1 and win.sel == 1, (len(win.project.clips), win.sel)
win.project.clips.pop(1)
win._refresh_timeline(select=0)
_e0 = len(win.project.effects)
win.project.effects.append({"id": "glitch", "intensity": 60, "start": 0.5, "end": 1.0})
win.fsel = len(win.project.effects) - 1
win.duplicate_selected()
assert len(win.project.effects) == _e0 + 2 and win.fsel == _e0 + 1, (len(win.project.effects), win.fsel)
del win.project.effects[_e0:]
win.fsel = -1
win._refresh_timeline(select=0)
win.sel = -1
win.duplicate_selected()                      # nichts gewählt: Meldung statt Absturz
win.sel = 0
no_errors("1.4.9: Duplizieren")
print("OK  1.4.9: Duplizieren")
# 1.5.0: Marker
win.project.markers = []
win.timeline.set_playhead(1.5)
win.add_marker()
assert [m["t"] for m in win.project.markers] == [1.5]
win.timeline.set_playhead(1.52)
win.add_marker()
assert win.project.markers == [], "M am selben Punkt entfernt den Marker"
win.timeline.set_playhead(0.5)
win.add_marker()
win.timeline.set_playhead(2.0)
win.add_marker()
_calls = []
win._seek_project = lambda t: _calls.append(round(t, 3))
win.timeline.set_playhead(0.0)
assert win.edit_key("next_marker") and _calls[-1] == 0.5
win.timeline.set_playhead(0.5)
win.edit_key("next_marker")
assert _calls[-1] == 2.0
win.timeline.set_playhead(2.0)
n_calls = len(_calls)
win.edit_key("next_marker")
assert len(_calls) == n_calls, "kein weiterer Marker: nicht springen"
win.edit_key("prev_marker")
assert _calls[-1] == 0.5
del win.__dict__["_seek_project"]
win.clear_markers()
assert win.project.markers == []
no_errors("1.5.0: Marker")
print("OK  1.5.0: Marker")
# 1.5.0: GIF-Export (nur der erste Schritt: Zwischenvideo klein und kurz rechnen)
_jobs = []
win._run_job = lambda cmd, total, title, on_done, measure="": _jobs.append((cmd, total, title, on_done))
assert win.run_gif_export("/tmp/x.gif", 320, 10) is True and len(_jobs) == 1
_cmd, _total, _title, _done = _jobs[0]
assert "vorbereitet" in _title and _cmd[-1].endswith("mid.mp4") and "-t" in _cmd, (_title, _cmd[-3:])
assert 0.1 < _total <= 30.0 + 1e-6
del win.__dict__["_run_job"]
no_errors("1.5.0: GIF-Export")
print("OK  1.5.0: GIF-Export")
# 1.5.0: Untertitel-Datei beim Export
import app.ui.main_window as _mw
_real_box, _real_find = _mw.QMessageBox, _mw.subs.find_whisper


class _FakeBox:
    asked = []
    answer = "yes"

    class StandardButton:
        Yes = "yes"
        No = "no"

    @classmethod
    def question(cls, *a, **k):
        cls.asked.append(a[1] if len(a) > 1 else "")
        return cls.answer

    information = warning = critical = question


_mw.QMessageBox = _FakeBox
try:
    from app.core.project import SubtitleCue as _Cue
    _saved_subs = win.project.subtitles
    win.project.sub_srt = False
    assert win._subs_before_export(lambda: None) is True and not _FakeBox.asked, "ohne Häkchen keine Frage"
    win.project.sub_srt = True
    win.project.subtitles = [_Cue(0.0, 1.0, "da")]
    assert win._subs_before_export(lambda: None) is True and not _FakeBox.asked, "mit Untertiteln keine Frage"
    win.project.subtitles = []
    _mw.subs.find_whisper = lambda: None
    assert win._subs_before_export(lambda: None) is True and len(_FakeBox.asked) == 1, "ohne Whisper nur ein Hinweis"
    _mw.subs.find_whisper = lambda: ("x", "y")
    _FakeBox.answer = "no"
    assert win._subs_before_export(lambda: None) is True and win._asr_then is None, "Nein: Export läuft ohne Datei"
    _FakeBox.answer = "yes"
    _started = []
    win.auto_subtitles = lambda: _started.append(1)
    assert win._subs_before_export(lambda: None) is True and win._asr_then is None, "Erkennung nicht gestartet: nichts merken"
    win.auto_subtitles = lambda: (setattr(win, "_asr_worker", object()), _started.append(2))
    ran = []
    assert win._subs_before_export(lambda: ran.append("export")) is False and win._asr_then is not None
    win.btn_asr = Stub()
    win._on_asr_done([_Cue(0.0, 1.0, "erkannt")], "")
    assert ran == ["export"] and win.project.subtitles and win._asr_then is None and win._asr_worker is None, "Export startet nach der Erkennung"
    win._asr_worker = object()
    win._asr_then = lambda: ran.append("falsch")
    win._on_asr_done(None, "Fehler")
    assert ran == ["export"], "bei Fehler startet der Export nicht"
    del win.__dict__["auto_subtitles"]
    # SRT-Datei schreiben
    import tempfile as _tf
    _vid = _os.path.join(_tf.mkdtemp(), "Film.mp4")
    win.project.sub_srt = False
    assert win._write_export_srt(_vid) == "" and not _os.path.exists(_vid[:-4] + ".srt")
    win.project.sub_srt = True
    assert "Film.srt" in win._write_export_srt(_vid) and _os.path.exists(_vid[:-4] + ".srt")
    win.project.subtitles = []
    assert "keine .srt" in win._write_export_srt(_vid)
    win.project.subtitles = _saved_subs
    win.project.sub_srt = False
    win.chk_sub_burn.setChecked(False)
    win._on_sub_export_changed()
    assert win.project.sub_burn is False
    win.chk_sub_burn.setChecked(True)
    win._on_sub_export_changed()
    assert win.project.sub_burn is True
finally:
    _mw.QMessageBox, _mw.subs.find_whisper = _real_box, _real_find
no_errors("1.5.0: Untertitel-Datei")
print("OK  1.5.0: Untertitel-Datei")
# 1.5.0: Drehung für Bild-in-Bild
win.project.overlays = [OverlayClip(_vid, 5.0, start=2.0, x_pct=70.0, y_pct=30.0, size_pct=30.0)]
win.osel = 0
win._load_overlay_fields()
_r = win.project.overlays[0]
win.ov_rot.setValue(30.0)
win._on_overlay_field()
assert _r.rot == 30.0, _r.rot
win.ov_kf_preset.setCurrentIndex(win.ov_kf_preset.findData("wobble"))
win._apply_ovk_preset()
assert _ok.active(_r) and all("rot" in k for k in _r.keys) and min(k["rot"] for k in _r.keys) == 20.0, _r.keys
win.ov_kf_pick.setCurrentIndex(1)
win.ov_kf_rot.setValue(-45.0)
win._on_ovk_field()
assert any(abs(k["rot"] + 45.0) < 1e-6 for k in _r.keys), _r.keys
win.clear_overlay_keys()
win.project.overlays = []
win.osel = -1
no_errors("1.5.0: Drehung Bild-in-Bild")
print("OK  1.5.0: Drehung Bild-in-Bild")
# 1.5.0: Standbild als PNG (erster Schritt: Zwischenvideo kurz rechnen)
_jobs = []
win._run_job = lambda cmd, total, title, on_done, measure="": _jobs.append((cmd, total, title, on_done))
assert win.run_still(1.0, "/tmp/still_test.png") is True and len(_jobs) == 1
assert "berechnet" in _jobs[0][2] and "-t" in _jobs[0][0] and "-ss" in _jobs[0][0]
del win.__dict__["_run_job"]
no_errors("1.5.0: Standbild")
print("OK  1.5.0: Standbild")
# 1.5.0: Beat-Sync (Anwenden; das Fenster selbst prüft ui_smoke)
win.asel = -1
assert win.detect_beats() is False, "ohne Audioblock nur ein Hinweis"
win.project.markers = []
_n_c = len(win.project.clips)
assert win.apply_beats([0.5 * k for k in range(1, 30)], True, True) is True
assert len(win.project.markers) == 29 and len(win.project.clips) == _n_c
win.project.markers = []
assert win.apply_beats([1.0], False, True) is False, "zu wenige Beats: Meldung, nichts geändert"
no_errors("1.5.0: Beat-Sync")
print("OK  1.5.0: Beat-Sync")
# 1.5.1: Mehrfachauswahl – gemeinsam löschen, duplizieren, Esc
win.fsel = win.osel = win.asel = -1
win.project.overlays = [OverlayClip(_vid, 5.0, start=1.0), OverlayClip(_vid, 5.0, start=7.0)]
win.project.effects = [{"id": "glitch", "intensity": 50, "start": 0.5, "end": 1.5}]
win._refresh_timeline(select=0)
_nc = len(win.project.clips)
win.timeline.set_multi([("o", 0), ("o", 1), ("f", 0)])
assert len(win.timeline.multi_items()) == 3
win.duplicate_selected()
assert len(win.project.overlays) == 4 and len(win.project.effects) == 2, (len(win.project.overlays), len(win.project.effects))
assert len(win.timeline.multi_items()) == 3, "die Kopien sind danach gewählt"
win.delete_selected()
assert len(win.project.overlays) == 2 or len(win.project.overlays) == 1, len(win.project.overlays)
assert not win.timeline.multi_items(), "nach dem Löschen keine Auswahl"
win.project.overlays = []
win.project.effects = []
win.timeline.set_multi([("v", 0), ("v", 0)])                      # doppelt = ein Eintrag = keine Mehrfachauswahl
assert not win.timeline.multi_items()
win.timeline.set_multi([("o", 0), ("f", 0)])                      # ungültig: Blöcke gibt es nicht mehr
assert not win.timeline.multi_items()
win.project.overlays = [OverlayClip(_vid, 5.0, start=1.0), OverlayClip(_vid, 5.0, start=7.0)]
win._refresh_timeline(select=0)
win.timeline.set_multi([("o", 0), ("o", 1)])
assert win.edit_key("esc") is True and not win.timeline.multi_items()
assert win.edit_key("esc") is False, "ohne Auswahl tut Esc nichts"
win.timeline.set_multi([("o", 0), ("o", 1)])
win.timeline.set_multi([("o", 0), ("o", 1)])
win._on_multi_changed()
win.timeline.clear_multi()
win.project.overlays = []
win._refresh_timeline(select=0)
assert len(win.project.clips) == _nc
# 1.5.1: Lücken schließen / Ripple-Löschen
win.fsel = win.osel = win.asel = -1
win.timeline.clear_multi()
_dur0 = win.project.duration
win.project.overlays = [OverlayClip(_vid, 5.0, 0.0, 1.0, start=0.2), OverlayClip(_vid, 5.0, 0.0, 1.0, start=_dur0 - 1.0)]
win.project.effects = []
win._refresh_timeline(select=0)
_c0 = win.project.clips[0].length
_ov_late = win.project.overlays[1].start
win.act_ripple_tracks.isChecked = lambda: True
assert win.ripple_delete_selected() >= 1
assert len(win.project.clips) == _nc - 1 and abs(win.project.duration - (_dur0 - _c0)) < 0.05, (len(win.project.clips), win.project.duration)
assert abs(win.project.overlays[-1].start - (_ov_late - _c0)) < 0.01 or len(win.project.overlays) == 1, [o.start for o in win.project.overlays]
win.undo() if hasattr(win, "undo") else None
win.project.overlays = [OverlayClip(_vid, 5.0, 0.0, 1.0, start=0.5), OverlayClip(_vid, 5.0, 0.0, 1.0, start=3.0)]
win._refresh_timeline(select=0)
assert win.close_all_gaps() == 1 and abs(win.project.overlays[1].start - 1.5) < 0.01, [o.start for o in win.project.overlays]
assert win.close_all_gaps() == 0, "ohne Lücken passiert nichts"
win.osel = 0
win.ripple_delete_selected()
assert len(win.project.overlays) == 1 and win.osel == -1, "gewähltes Bild-in-Bild wird einfach gelöscht"
win.project.overlays = []
no_errors("1.5.1: Ripple")
print("OK  1.5.1: Ripple")
# 1.5.1: Standbild einfügen
import app.core.freeze as _fz
from PIL import Image
win.project.overlays = []
win._refresh_timeline(select=0)
_nc2 = len(win.project.clips)
_dur2 = win.project.duration
_real_extract = _fz.extract
_fz.extract = lambda clip, local, png: Image.new("RGB", (64, 36), (0, 0, 255)).save(png)
win.timeline.set_playhead(min(1.0, _dur2 / 2))
assert win.insert_freeze(2.0) is True
assert len(win.project.clips) in (_nc2 + 1, _nc2 + 2) and abs(win.project.duration - (_dur2 + 2.0)) < 0.05, (len(win.project.clips), win.project.duration)
assert any(c.is_image and abs(c.length - 2.0) < 1e-6 for c in win.project.clips)
_img_i = [i for i, c in enumerate(win.project.clips) if c.is_image][0]
win.timeline.set_playhead(win.project.clip_start(_img_i) + 0.5)
assert win.insert_freeze(2.0) is False, "auf einem Standbild wird kein weiteres Standbild gemacht"
_fz.extract = _real_extract
win.project.clips = [c for c in win.project.clips if not c.is_image]
win._refresh_timeline(select=0)
no_errors("1.5.1: Standbild einfügen")
print("OK  1.5.1: Standbild einfügen")
# 1.5.1: YouTube-Kapitel
_dc = win.project.duration
win.project.markers = [{"t": 0.0, "name": "Start"}, {"t": _dc * 0.4, "name": "Mitte"}, {"t": _dc * 0.6, "name": ""}]
dlg = win.build_chapters_dialog()
assert dlg._result["text"].startswith("0:00 Start") and "Mitte" in dlg._result["text"] and "Marker ohne Namen" in " ".join(dlg._result["notes"]), dlg._result
dlg._edit.setText("Los")
win.project.markers = [{"t": _dc * 0.4, "name": "Mitte"}]
dlg._refresh()
assert dlg._result["items"][0][1] in ("Los", "Anfang"), dlg._result["items"]
dlg._copy()
win.project.markers = []
no_errors("1.5.1: YouTube-Kapitel")
print("OK  1.5.1: YouTube-Kapitel")
# 1.5.1: Projekt sammeln
import os
import tempfile as _tf51
_cd = _tf51.mkdtemp(prefix="fate_col_")
_r = win.run_collect(os.path.join(_cd, "ziel"), False, "T", show_progress=False)
assert _r is not None and _r["files"] >= 1 and os.path.isfile(_r["project"]), _r
_r2 = win.run_collect(os.path.join(_cd, "t.zip"), True, "T", show_progress=False)
assert _r2 is not None and os.path.isfile(os.path.join(_cd, "t.zip"))
assert win.run_collect(os.path.join(_cd, "x", "y", "ziel"), False, "T", show_progress=False) is not None
no_errors("1.5.1: Projekt sammeln")
print("OK  1.5.1: Projekt sammeln")
no_errors("1.5.1: Mehrfachauswahl")
print("OK  1.5.1: Mehrfachauswahl")
print("Signal-Prüfung OK")
