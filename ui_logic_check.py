"""Prüft die Python-Logik des Hauptfensters OHNE echtes Qt (Attrappen-Module).

Findet Tippfehler, falsche Namen und Logikfehler. Ersetzt NICHT den echten Start-Test
(tests/ui_smoke.py mit PySide6) – der läuft zusätzlich auf GitHub.
"""
import sys, types, subprocess, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"): raise AttributeError(name)
        v = Stub(); setattr(cls, name, v); return v


class Stub(metaclass=_Meta):
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return Stub()
    def __getattr__(self, name):
        if name.startswith("__"): raise AttributeError(name)
        v = Stub(); object.__setattr__(self, name, v); return v
    def __iter__(self): return iter(())
    def __lt__(self, o): return False
    __gt__ = __le__ = __ge__ = __lt__
    def __int__(self): return 0
    def __index__(self): return 0
    def __float__(self): return 0.0
    def __or__(self, o): return Stub()
    __ror__ = __or__
    def connect(self, *a, **k): pass
    def emit(self, *a, **k): pass


def Signal(*a, **k): return Stub()

def make(name, attrs=()):
    m = types.ModuleType(name)
    m.__getattr__ = lambda n: Stub if n[0].isupper() else (_ for _ in ()).throw(AttributeError(n))
    for k, v in attrs: setattr(m, k, v)
    sys.modules[name] = m
    return m

make("PySide6"); make("PySide6.QtCore", [("Signal", Signal)]); make("PySide6.QtGui")
make("PySide6.QtWidgets"); make("PySide6.QtMultimedia"); make("PySide6.QtMultimediaWidgets")
import PySide6.QtCore as C
class QThread(Stub): pass
C.QThread = QThread

from app.ui import main_window as mw
from app.core.project import Project

win = mw.MainWindow()
print("Fenster erzeugt")

tmp = Path(tempfile.mkdtemp())
vid = tmp / "t.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=5",
                "-f", "lavfi", "-i", "sine=duration=5", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(vid)], check=True)
win.import_files([str(vid)])
assert len(win.project.clips) == 1, "Auto-Hinzufügen beim ersten Import"
win._add_to_timeline(str(vid))
assert len(win.project.clips) == 2
win.sel = 0
win.delete_clip(); assert len(win.project.clips) == 1
# Teilen
win.sel = 0; win._cur_path = str(vid)
class P:  # Player-Attrappe
    def position(self): return 2000
win.player = P(); win.split_clip()
assert len(win.project.clips) == 2 and abs(win.project.clips[0].out_pt - 2.0) < 1e-6, win.project.clips
win.move_clip(1)
# Effekte setzen
win._fx_state["glitch"] = {"intensity": 80, "start": 0.0, "end": 3.0}
class It:
    def __init__(s, eid): s.eid = eid
    def checkState(s, c): return mw.Qt.CheckState.Checked
    def data(s, c, r): return s.eid
win._fx_items = lambda: [It("glitch"), It("vhs")]
win._collect_effects()
print("Effekte:", win.project.effects)
assert win.project.effects[0]["end"] == 3.0
# Text
win.add_text(); t0 = win.project.texts[0]; t0.text = "Test äöü"; t0.font = ""; t0.start = 0.0; t0.end = 2.0; t0.size_pct = 7.0
# Export-Befehl bauen und ausführen
from app.core import exporter
cmd, total, t = exporter.build_command(win.project, str(tmp / "o.mp4"))
exporter.run(cmd, total)
print("Export ok, Dauer", round(total, 2))
# Projekt speichern/laden
win.project.save(str(tmp / "p.cforge")); p2 = Project.load(str(tmp / "p.cforge"))
assert len(p2.clips) == len(win.project.clips) and p2.effects == win.project.effects
print("UI-Logik OK")
