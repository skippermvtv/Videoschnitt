"""Prüft die Mauslogik der Timeline (Verschieben, Kürzen, Einrasten, Spurwechsel) mit einfachen Attrappen statt Qt."""
import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class Sig:
    def __init__(s, *a): s.calls = []
    def emit(s, *a): s.calls.append(a)
    def connect(s, f): pass

class Any:
    def __getattr__(s, n): return Any()
    def __call__(s, *a, **k): return Any()

class QRectF:
    def __init__(s, x=0, y=0, w=0, h=0): s.x, s.y, s.w, s.h = x, y, w, h
    def left(s): return s.x
    def right(s): return s.x + s.w
    def top(s): return s.y
    def height(s): return s.h
    def contains(s, p): return s.x <= p.x() <= s.x + s.w and s.y <= p.y() <= s.y + s.h

class Pt:
    def __init__(s, x, y): s._x, s._y = x, y
    def x(s): return s._x
    def y(s): return s._y

class Ev:
    def __init__(s, x, y): s._p = Pt(x, y)
    def position(s): return s._p

class QWidget:
    def __init__(s, parent=None): s._w, s._h = 1000, 260
    def width(s): return s._w
    def height(s): return s._h
    def setMinimumHeight(s, h): pass
    def setMouseTracking(s, b): pass
    def setCursor(s, c): pass
    def update(s): pass
    def font(s): return Any()
    def setAcceptDrops(s, b): pass
    def window(s): return s._win if hasattr(s, "_win") else s

def mod(name, **kw):
    m = types.ModuleType(name)
    for k, v in kw.items(): setattr(m, k, v)
    sys.modules[name] = m
    return m

mod("PySide6")
mod("PySide6.QtCore", QRectF=QRectF, Qt=Any(), Signal=lambda *a: Sig())
mod("PySide6.QtGui", QColor=Any, QFont=Any, QPainter=Any, QPen=Any)
mod("PySide6.QtWidgets", QWidget=QWidget)

# Signal ist im echten Qt ein Klassenattribut; hier pro Instanz neu anlegen
import app.ui.timeline as tl
orig_init = tl.Timeline.__init__
def init(self, parent=None):
    orig_init(self, parent)
    self.clip_selected, self.audio_selected, self.audio_edited = Sig(), Sig(), Sig()
    self.clip_edited, self.clip_reordered, self.seek_requested = Sig(), Sig(), Sig()
    self.overlay_selected, self.overlay_edited = Sig(), Sig()
    self.fx_selected, self.fx_edited, self.effect_dropped = Sig(), Sig(), Sig()
tl.Timeline.__init__ = init

from app.core.project import AudioClip, Clip, OverlayClip, Project

p = Project()
p.clips = [Clip("a.mp4", 10.0), Clip("b.mp4", 10.0)]       # 20 s
p.audio_clips = [AudioClip("m.wav", 8.0, start=2.0, track=2)]
t = tl.Timeline()
t.set_project(p, 0, -1)
# Rechtecke wie beim Zeichnen berechnen
t._arects = []
a = p.audio_clips[0]
def rects():
    t._vrects, t._arects = [], []
    for k, c in enumerate(p.clips):
        t._vrects.append(QRectF(t._x(p.clip_start(k)) + 1, t._lane_y(0), c.length / t._span() * t._avail() - 2, tl.V_H))
    for i, x in enumerate(p.audio_clips):
        t._arects.append((i, QRectF(t._x(x.start), t._lane_y(x.track), x.length / t._span() * t._avail(), tl.A_H)))
rects()
px = t._avail() / t._total()               # Pixel pro Sekunde
ym = t._lane_y(2) + 10
x_mid = t._x(a.start) + 30

# 1) Klick auf Video wählt Clip
t.mousePressEvent(Ev(t._x(15), t._lane_y(0) + 10)); assert t.clip_selected.calls[-1] == (1,), t.clip_selected.calls
# 2) Verschieben um +3 s (kein Einrasten in Reichweite)
t.mousePressEvent(Ev(x_mid, ym)); assert t.audio_selected.calls[-1] == (0,)
t.mouseMoveEvent(Ev(x_mid + 3.37 * px, ym)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(a.start - 5.37) < 0.01, a.start
# 3) Einrasten am Clipende bei 10 s (Block-Start 9.9 s -> 10.0)
rects(); x_mid = t._x(a.start) + 30
t.mousePressEvent(Ev(x_mid, ym)); t.mouseMoveEvent(Ev(x_mid + (9.9 - a.start) * px, ym)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(a.start - 10.0) < 1e-6, a.start
# 4) Spurwechsel A2 -> A3 und nicht vor 0 s
rects(); x_mid = t._x(a.start) + 30
t.mousePressEvent(Ev(x_mid, ym)); t.mouseMoveEvent(Ev(x_mid - 50 * px, t._lane_y(3) + 8)); t.mouseReleaseEvent(Ev(0, 0))
assert a.start == 0.0 and a.track == 3, (a.start, a.track)
# 5) Rechter Rand kürzen: 8 s -> ca. 5 s
rects(); r = t._arects[0][1]
t.mousePressEvent(Ev(r.right() - 2, t._lane_y(3) + 8)); assert t._drag["mode"] == "trim_r"
t.mouseMoveEvent(Ev(r.right() - 2 - 3.3 * px, t._lane_y(3) + 8)); t.mouseReleaseEvent(Ev(0, 0))
assert 4.5 < a.out_pt < 5.0, a.out_pt
# 6) Linker Rand: Anfang abschneiden -> in_pt wächst, Start rückt nach rechts, Ende bleibt
rects(); r = t._arects[0][1]; end_before = a.start + a.length
t.mousePressEvent(Ev(r.left() + 2, t._lane_y(3) + 8)); assert t._drag["mode"] == "trim_l"
t.mouseMoveEvent(Ev(r.left() + 2 + 1.5 * px, t._lane_y(3) + 8)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(a.in_pt - 1.5) < 0.05 and abs(a.start - 1.5) < 0.05 and abs(a.start + a.length - end_before) < 0.05, (a.in_pt, a.start)
# 7) Verknüpfter Videoton: link_offset folgt dem Verschieben
p.detach_audio(1); v = p.audio_clips[1]; assert v.start == 10.0
rects(); xm = t._x(v.start) + 30
t.mousePressEvent(Ev(xm, t._lane_y(1) + 8)); t.mouseMoveEvent(Ev(xm + 2 * px, t._lane_y(1) + 8)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(v.link_offset - 2.0) < 0.05, v.link_offset
p.clips.reverse(); p.sync_linked()
assert abs(v.start - (p.clip_start(p.clip_index(v.link)) + v.link_offset)) < 1e-6

# 8) Videoclip kürzen (rechter und linker Rand), danach zurücksetzen
p.audio_clips = []; p.clips = [Clip("a.mp4", 10.0), Clip("b.mp4", 10.0)]
rects(); r = t._vrects[0]; y = t._lane_y(0) + 10
t.mousePressEvent(Ev(r.right() - 2, y)); assert t._drag["kind"] == "v" and t._drag["mode"] == "trim_r"
t.mouseMoveEvent(Ev(r.right() - 2 - 2 * px, y)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(p.clips[0].out_pt - 8.0) < 0.05, p.clips[0].out_pt
assert t.clip_edited.calls and t.clip_edited.calls[-1] == (0,)
rects(); r = t._vrects[0]; px = t._avail() / t._span()
t.mousePressEvent(Ev(r.left() + 2, y)); assert t._drag["mode"] == "trim_l"
t.mouseMoveEvent(Ev(r.left() + 2 + 1 * px, y)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(p.clips[0].in_pt - 1.0) < 0.05
# 9) Umsortieren: Clip 0 hinter Clip 1 ziehen
rects(); r0, r1 = t._vrects
t.mousePressEvent(Ev(r0.left() + 40, y)); assert t._drag["mode"] == "move"
t.mouseMoveEvent(Ev(r1.right() - 20, y)); assert t._drop_t >= 0
t.mouseReleaseEvent(Ev(0, 0)); assert t.clip_reordered.calls[-1] == (0, 1), t.clip_reordered.calls
# kleiner Ruck ohne echtes Ziehen ändert nichts
n = len(t.clip_reordered.calls); rects(); r0 = t._vrects[0]
t.mousePressEvent(Ev(r0.left() + 40, y)); t.mouseMoveEvent(Ev(r0.left() + 42, y)); t.mouseReleaseEvent(Ev(0, 0))
assert len(t.clip_reordered.calls) == n
# 10) Klick aufs Lineal -> Seek
t.mousePressEvent(Ev(t._x(7.0), 10)); assert abs(t.seek_requested.calls[-1][0] - 7.0) < 0.05
t.mouseReleaseEvent(Ev(0, 0))
# 11) Zoom: Zeit-zu-Pixel passt, Ausschnitt bleibt gültig
t.zoom_by(4.0, 10.0); assert abs(t.zoom - 4.0) < 1e-9 and 0 <= t._view0 <= t._total() - t._span()
assert abs(t._t_at(t._x(12.5)) - 12.5) < 1e-6
t.zoom_by(100.0); assert t.zoom == tl.MAX_ZOOM
t.zoom_fit(); assert t.zoom == 1.0 and t._view0 == 0.0

# 12) Bild-in-Bild-Spur oben: verschieben und kürzen
assert t._lane_y(4) < t._lane_y(0) < t._lane_y(1) < t._lane_y(3)
p.overlays = [OverlayClip("o.mp4", 6.0, 0.0, 6.0, start=1.0)]
t._orects = [(0, QRectF(t._x(1.0), t._lane_y(4), 6.0 / t._span() * t._avail(), tl.V2_H))]
px = t._avail() / t._span(); yo = t._lane_y(4) + 8
t.mousePressEvent(Ev(t._x(3.0), yo)); assert t.overlay_selected.calls[-1] == (0,) and t._drag["kind"] == "o"
t.mouseMoveEvent(Ev(t._x(3.0) + 4.1 * px, yo)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(p.overlays[0].start - 5.1) < 0.1, p.overlays[0].start
t._orects = [(0, QRectF(t._x(5.1), t._lane_y(4), 6.0 / t._span() * t._avail(), tl.V2_H))]
r = t._orects[0][1]
t.mousePressEvent(Ev(r.right() - 2, yo)); assert t._drag["mode"] == "trim_r"
t.mouseMoveEvent(Ev(r.right() - 2 - 3 * px, yo)); t.mouseReleaseEvent(Ev(0, 0))
assert 2.5 < p.overlays[0].out_pt < 3.5, p.overlays[0].out_pt

# 13) Effekt-Spur (FX) ganz oben: anlegen, verschieben, kürzen, Zeilen, Ablegen aus der Liste
p.audio_clips, p.overlays = [], []
p.clips = [Clip("a.mp4", 10.0), Clip("b.mp4", 10.0)]      # 20 s
p.effects = []
assert t._lane_y(5) < t._lane_y(4) < t._lane_y(0), "FX muss die oberste Spur sein"
i = p.fx_add("glitch", 70, 2.0)                           # 2 … 5 s
t.set_project(p, 0, -1, -1, -1)
def frects():
    t._frects = []
    for k in range(len(p.effects)):
        f0, f1 = p.fx_span(k)
        row = t._fx_rows[k]
        t._frects.append((k, QRectF(t._x(f0), t._lane_y(5) + 3.0 + row * tl.FX_ROW_H, (f1 - f0) / t._span() * t._avail(), tl.FX_ROW_H - 2.0)))
frects()
px = t._avail() / t._span(); yf = t._lane_y(5) + 3.0 + 6
t.mousePressEvent(Ev(t._x(3.5), yf)); assert t.fx_selected.calls[-1] == (0,) and t._drag["kind"] == "f" and t._drag["mode"] == "move"
t.mouseMoveEvent(Ev(t._x(3.5) + 4.0 * px, yf)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(p.fx_span(0)[0] - 6.0) < 0.1 and abs(p.fx_span(0)[1] - 9.0) < 0.1, p.fx_span(0)
assert t.fx_edited.calls and t.fx_edited.calls[-1] == (0,)
frects(); r = t._frects[0][1]
t.mousePressEvent(Ev(r.right() - 2, yf)); assert t._drag["mode"] == "trim_r"
t.mouseMoveEvent(Ev(r.right() - 2 + 2.0 * px, yf)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(p.fx_span(0)[1] - 11.0) < 0.15 and abs(p.fx_span(0)[0] - 6.0) < 0.1, p.fx_span(0)
frects(); r = t._frects[0][1]
t.mousePressEvent(Ev(r.left() + 2, yf)); assert t._drag["mode"] == "trim_l"
t.mouseMoveEvent(Ev(r.left() + 2 - 1.0 * px, yf)); t.mouseReleaseEvent(Ev(0, 0))
assert abs(p.fx_span(0)[0] - 5.0) < 0.15, p.fx_span(0)
# bis ans Projektende ziehen -> "bis Ende", ganz vorn + bis Ende -> keine Zeiten gespeichert
frects(); r = t._frects[0][1]
t.mousePressEvent(Ev(r.right() - 2, yf)); t.mouseMoveEvent(Ev(r.right() + 40 * px, yf)); t.mouseReleaseEvent(Ev(0, 0))
assert p.effects[0].get("end") is None and abs(p.fx_span(0)[1] - 20.0) < 1e-6, p.effects[0]
frects(); r = t._frects[0][1]
t.mousePressEvent(Ev(r.left() + 2, yf)); t.mouseMoveEvent(Ev(r.left() + 2 - 60 * px, yf)); t.mouseReleaseEvent(Ev(0, 0))
assert "start" not in p.effects[0] and "end" not in p.effects[0] and p.fx_span(0) == (0.0, 20.0), p.effects[0]
# zwei überlappende Blöcke liegen in zwei Zeilen, die Spur wird höher
h1 = t._lane_h(5)
p.fx_add("vhs", 50, 1.0, 5.0)
t.set_project(p, 0, -1, -1, 0)
assert t._fx_rows == [0, 1] and t._lane_h(5) > h1, (t._fx_rows, h1, t._lane_h(5))
assert t._lane_y(4) > t._lane_y(5) + t._lane_h(5) - 1e-6, "darunterliegende Spuren müssen nach unten rutschen"
# Ablegen aus der Effektliste
class Mime:
    def __init__(s, text="", urls=False): s._t, s._u = text, urls
    def hasText(s): return bool(s._t)
    def text(s): return s._t
    def hasUrls(s): return s._u
class DEv(Ev):
    def __init__(s, x, y, mime): super().__init__(x, y); s._m = mime; s.acc = None
    def mimeData(s): return s._m
    def acceptProposedAction(s): s.acc = True
    def ignore(s): s.acc = False
assert abs(t.effect_drop("glitch", t._x(7.0)) - 7.0) < 0.05
assert t.effect_drop("gibtsnicht", t._x(7.0)) is None and t.effect_drop("glitch", 2) is None
e = DEv(t._x(7.0), yf, Mime(tl.FX_MIME + "glitch")); t.dragEnterEvent(e); assert e.acc is True
t.dropEvent(e); assert t.effect_dropped.calls[-1][0] == "glitch" and abs(t.effect_dropped.calls[-1][1] - 7.0) < 0.05
n = len(t.effect_dropped.calls)
e = DEv(2, yf, Mime(tl.FX_MIME + "glitch")); t.dropEvent(e); assert e.acc is False and len(t.effect_dropped.calls) == n
# Dateien auf der Timeline werden an das Hauptfenster weitergereicht (Import wie bisher)
class Win:
    def __init__(s): s.got = []
    def dragEnterEvent(s, ev): s.got.append("enter")
    def dropEvent(s, ev): s.got.append("drop")
t._win = Win()
t.dragEnterEvent(DEv(5, 5, Mime("", urls=True))); t.dropEvent(DEv(5, 5, Mime("", urls=True)))
assert t._win.got == ["enter", "drop"], t._win.got
print("OK  Effekt-Spur (FX): verschieben, kürzen, Zeilen, Ablegen")
print("Timeline-Mauslogik OK")
