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
print("Signal-Prüfung OK")
