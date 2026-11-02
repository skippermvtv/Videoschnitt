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
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
                "-f", "lavfi", "-i", "sine=duration=4", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(vid)], check=True)
wav = tmp / "m.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=500:duration=2", str(wav)], check=True)
png = tmp / "i.png"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=200x200:d=1", "-frames:v", "1", str(png)], check=True)

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
print("Signal-Prüfung OK")
