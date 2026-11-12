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
    def __init__(s, x=0, y=0, w=0, h=0):
        if hasattr(x, "x") and hasattr(y, "x"):                # QRectF(QPointF, QPointF)
            x, y, w, h = x.x(), x.y(), y.x() - x.x(), y.y() - x.y()
        s.x, s.y, s.w, s.h = x, y, w, h
    def normalized(s):
        return QRectF(min(s.x, s.x + s.w), min(s.y, s.y + s.h), abs(s.w), abs(s.h))
    def intersects(s, o):
        return s.x < o.x + o.w and o.x < s.x + s.w and s.y < o.y + o.h and o.y < s.y + s.h
    def left(s): return s.x
    def right(s): return s.x + s.w
    def top(s): return s.y
    def height(s): return s.h
    def contains(s, p): return s.x <= p.x() <= s.x + s.w and s.y <= p.y() <= s.y + s.h
    def width(s): return s.w
    def center(s): return Pt(s.x + s.w / 2, s.y + s.h / 2)

class QPointF:
    def __init__(s, x=0, y=0): s._x, s._y = x, y
    def x(s): return s._x
    def y(s): return s._y

class Pt:
    def __init__(s, x, y): s._x, s._y = x, y
    def x(s): return s._x
    def y(s): return s._y

class Ev:
    def __init__(s, x, y, mods=0): s._p, s._m = Pt(x, y), mods
    def position(s): return s._p
    def modifiers(s): return s._m
    def button(s): return "L"

class QtStub(Any):
    MouseButton = types.SimpleNamespace(LeftButton="L")
    KeyboardModifier = types.SimpleNamespace(ControlModifier=1, ShiftModifier=2)

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
    def mouseDoubleClickEvent(s, e): s.fallback = True
    def window(s): return s._win if hasattr(s, "_win") else s

def mod(name, **kw):
    m = types.ModuleType(name)
    for k, v in kw.items(): setattr(m, k, v)
    sys.modules[name] = m
    return m

mod("PySide6")
mod("PySide6.QtCore", QPointF=QPointF, QRectF=QRectF, Qt=QtStub(), Signal=lambda *a: Sig())
mod("PySide6.QtGui", QColor=Any, QFont=Any, QPainter=Any, QPen=Any, QPolygonF=Any)
mod("PySide6.QtWidgets", QWidget=QWidget)

# Signal ist im echten Qt ein Klassenattribut; hier pro Instanz neu anlegen
import app.ui.timeline as tl
orig_init = tl.Timeline.__init__
def init(self, parent=None):
    orig_init(self, parent)
    self.clip_selected, self.audio_selected, self.audio_edited = Sig(), Sig(), Sig()
    self.clip_edited, self.clip_reordered, self.seek_requested = Sig(), Sig(), Sig()
    self.overlay_selected, self.overlay_edited, self.overlay_key_requested = Sig(), Sig(), Sig()
    self.fx_selected, self.fx_edited, self.effect_dropped = Sig(), Sig(), Sig()
    self.media_dropped, self.lane_mute_toggled = Sig(), Sig()
    self.title_dropped, self.transition_dropped = Sig(), Sig()
    self.multi_changed, self.multi_edited = Sig(), Sig()
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
# 1.4.6: gleichzeitig laufende Bild-in-Bild-Blöcke liegen in eigenen Zeilen, die Spur wird höher
p.overlays = [OverlayClip("a.mp4", 6.0, 0.0, 6.0, start=1.0)]
t.set_project(p, 0, -1, 0, -1)
assert t._ov_rows == [0] and t._ov_row_count() == 1 and t._lane_h(4) == tl.V2_H, (t._ov_rows, t._lane_h(4))
p.overlays = [OverlayClip("a.mp4", 6.0, 0.0, 6.0, start=1.0), OverlayClip("b.mp4", 6.0, 0.0, 6.0, start=2.0),
              OverlayClip("c.mp4", 3.0, 0.0, 3.0, start=9.0)]
t.set_project(p, 0, -1, -1, -1)
assert t._ov_rows == [0, 1, 0] and t._ov_row_count() == 2 and t._lane_h(4) > tl.V2_H, (t._ov_rows, t._lane_h(4))
assert t._lane_y(0) > t._lane_y(4) + t._lane_h(4) - 1e-6 or t._lane_y(1) > t._lane_y(4) + t._lane_h(4) - 1e-6, "Spuren darunter rutschen nach unten"
p.overlays = []
t.set_project(p, 0, -1, -1, -1)
assert t._ov_rows == [] and t._lane_h(4) == tl.V2_H
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
# 1.4.1: Medien aus dem Raster ablegen (Einfügeposition) und Spurköpfe (Stumm / Sperren)
t._win = Win()
t.set_project(p, 0, -1, -1, 0)
assert t.media_drop_index(0.5) == 0 and t.media_drop_index(4.0) == 0 and t.media_drop_index(6.0) == 1 and t.media_drop_index(19.0) == 2, \
    [t.media_drop_index(x) for x in (0.5, 4.0, 6.0, 19.0)]
assert t._mime_media(Mime(tl.MEDIA_MIME + "a.mp4\nb.png")) == ["a.mp4", "b.png"] and t._mime_media(Mime("nix")) == []
e = DEv(t._x(12.0), yf, Mime(tl.MEDIA_MIME + "a.mp4\nb.png")); t.dragEnterEvent(e); assert e.acc is True
e = DEv(t._x(12.0), yf, Mime(tl.MEDIA_MIME + "a.mp4\nb.png")); t.dragMoveEvent(e); assert e.acc is True and t._drop_t == p.clip_start(1)
e = DEv(t._x(12.0), yf, Mime(tl.MEDIA_MIME + "a.mp4\nb.png")); t.dropEvent(e)
assert t.media_dropped.calls[-1] == (["a.mp4", "b.png"], 1), t.media_dropped.calls
assert t._drop_t == -1.0
p.audio_clips = [a]                            # der FX-Teil oben hat die Tonblöcke geleert
t.set_project(p, 0, -1, -1, 0)
TR = a.track                                   # der Tonblock liegt nach den Tests oben evtl. auf einer anderen Spur
hb = t._header_buttons(TR)
assert set(hb) == {"mute", "lock"} and set(t._header_buttons(0)) == {"lock"} and set(t._header_buttons(5)) == {"lock"}
mx, my = hb["mute"].left() + 3, hb["mute"].top() + 3
t.mousePressEvent(Ev(mx, my)); assert t.lane_mute_toggled.calls[-1] == (TR,), t.lane_mute_toggled.calls
n_sel = len(t.audio_selected.calls)
lx, ly = hb["lock"].left() + 3, hb["lock"].top() + 3
t.mousePressEvent(Ev(lx, ly)); assert t.is_locked(TR)
rects()
t.mousePressEvent(Ev(t._x(a.start) + 30, t._lane_y(TR) + 10))
assert len(t.audio_selected.calls) == n_sel, "gesperrte Spur darf nichts auswählen"
t.mousePressEvent(Ev(lx, ly)); assert not t.is_locked(TR)
t.mousePressEvent(Ev(t._x(a.start) + 30, t._lane_y(TR) + 10))
assert len(t.audio_selected.calls) == n_sel + 1, "entsperrt wählt wieder aus"
t.mousePressEvent(Ev(t._lane_y(0), t._lane_y(0) + 5))      # Klick im Kopf ohne Schalter: nichts passiert
print("OK  Medien ablegen, Spurköpfe")
# 1.4.2: Titel und Übergänge aus den Listen ablegen
p.audio_clips = []
t.set_project(p, 0, -1, -1, 0)
assert t.trans_drop_index(9.0) == 0 and t.trans_drop_index(0.0) == 0 and t.trans_drop_index(19.0) == 0     # zwei Clips → nur eine Grenze
e = DEv(t._x(4.0), yf, Mime(tl.TITLE_MIME + "lower_third")); t.dragEnterEvent(e); assert e.acc is True
t.dragMoveEvent(e); assert e.acc is True and abs(t._drop_t - 4.0) < 0.05
e = DEv(t._x(4.0), yf, Mime(tl.TITLE_MIME + "lower_third")); t.dropEvent(e)
assert t.title_dropped.calls[-1][0] == "lower_third" and abs(t.title_dropped.calls[-1][1] - 4.0) < 0.05 and t._drop_t == -1.0
e = DEv(t._x(9.0), yf, Mime(tl.TRANS_MIME + "fade")); t.dragEnterEvent(e); assert e.acc is True
t.dragMoveEvent(e); assert e.acc is True and t._drop_t == 10.0
e = DEv(t._x(9.0), yf, Mime(tl.TRANS_MIME + "fade")); t.dropEvent(e)
assert t.transition_dropped.calls[-1] == ("fade", 0), t.transition_dropped.calls
p1 = Project(); p1.clips = [Clip("a.mp4", 10.0)]
t.set_project(p1, 0, -1, -1, 0)
assert t.trans_drop_index(5.0) == -1
e = DEv(t._x(5.0), yf, Mime(tl.TRANS_MIME + "fade")); t.dragMoveEvent(e); assert e.acc is False
n_tr = len(t.transition_dropped.calls)
e = DEv(t._x(5.0), yf, Mime(tl.TRANS_MIME + "fade")); t.dropEvent(e); assert e.acc is False and len(t.transition_dropped.calls) == n_tr
print("OK  Titel und Übergänge ablegen")
t.set_locked([3, 0, 99]) if False else None
t._locked = set()
t.set_locked([3, 0, 5, 3])
assert t.locked_lanes() == [0, 3, 5] and t.is_locked(3) and not t.is_locked(1)
t.set_locked([])
assert t.locked_lanes() == []
print("OK  Spursperren setzen/lesen")
# Doppelklick auf einen Bild-in-Bild-Block fügt einen Keyframe ein; Rauten-Positionen
from app.core import overlaykeys
p.overlays = [OverlayClip("k.mp4", 6.0, 0.0, 6.0, start=1.0)]
t.set_project(p, 0, -1, 0)
rk = QRectF(t._x(1.0), t._lane_y(4), 6.0 / t._span() * t._avail(), tl.V2_H)
t._orects = [(0, rk)]
assert t.overlay_key_points(0, rk) == []
t.overlay_key_requested.calls.clear(); t.overlay_selected.calls.clear()
t.mouseDoubleClickEvent(Ev(t._x(4.0), t._lane_y(4) + 5))                    # 4 s = 50 % im Block (1…7 s)
assert t.overlay_key_requested.calls and abs(t.overlay_key_requested.calls[0][1] - 0.5) < 0.01, t.overlay_key_requested.calls
assert t.overlay_key_requested.calls[0][0] == 0 and t.overlay_selected.calls
t.overlay_key_requested.calls.clear()
t.mouseDoubleClickEvent(Ev(t._x(15.0), t._lane_y(4) + 5))                   # neben dem Block: nichts
assert not t.overlay_key_requested.calls
t._locked = {4}
t.mouseDoubleClickEvent(Ev(t._x(4.0), t._lane_y(4) + 5))                    # Spur gesperrt: nichts
assert not t.overlay_key_requested.calls
t._locked = set()
p.overlays[0].cell = [0, 0, 50, 50]
t.mouseDoubleClickEvent(Ev(t._x(4.0), t._lane_y(4) + 5))                    # Split-Feld: keine Keyframes
assert not t.overlay_key_requested.calls
p.overlays[0].cell = []
overlaykeys.apply_preset("swing", p.overlays[0])
pts = t.overlay_key_points(0, rk)
assert len(pts) == 3 and abs(pts[0].x() - rk.left()) < 1e-6 and abs(pts[2].x() - rk.right()) < 1e-6 \
    and abs(pts[1].x() - (rk.left() + rk.width() / 2)) < 1e-6
print("OK  Bild-in-Bild: Doppelklick fügt Keyframe ein, Rauten")
p.markers = [{"t": 3.21, "name": ""}]
assert 3.21 in t._snap_points(-1), "Marker sind Einrastpunkte"
assert abs(t._snap(3.23, t._snap_points(-1)) - 3.21) < 1e-9, "Marker zieht an"
p.markers = []
print("OK  Marker: Einrasten")
# ---- Mehrfachauswahl (1.5.1)
CTRL = 1
p2 = Project()
p2.clips = [Clip("a.mp4", 10.0), Clip("b.mp4", 10.0)]                               # 20 s
p2.audio_clips = [AudioClip("m.wav", 8.0, start=2.0, track=2), AudioClip("n.wav", 4.0, start=12.0, track=3)]
p2.overlays = [OverlayClip("o.mp4", 5.0, start=3.0), OverlayClip("q.mp4", 4.0, start=10.0)]
p2.effects = [{"id": "glitch", "intensity": 50, "start": 5.0, "end": 8.0}]
t2 = tl.Timeline()
t2.set_project(p2, 0, -1)
px2 = t2._avail() / t2._total()


def rects2():
    t2._vrects, t2._arects, t2._orects, t2._frects = [], [], [], []
    for k, c in enumerate(p2.clips):
        t2._vrects.append(QRectF(t2._x(p2.clip_start(k)) + 1, t2._lane_y(0), c.length / t2._span() * t2._avail() - 2, tl.V_H))
    for i, x in enumerate(p2.audio_clips):
        t2._arects.append((i, QRectF(t2._x(x.start), t2._lane_y(x.track), x.length / t2._span() * t2._avail(), tl.A_H)))
    for i, o in enumerate(p2.overlays):
        t2._orects.append((i, QRectF(t2._x(o.start), t2._lane_y(4), o.length / t2._span() * t2._avail(), 20)))
    for i in range(len(p2.effects)):
        s0, e0 = p2.fx_span(i)
        t2._frects.append((i, QRectF(t2._x(s0), t2._lane_y(tl.FX_LANE) + 3, (e0 - s0) / t2._span() * t2._avail(), 18)))


def center(r):
    return r.x + r.w / 2, r.y + r.h / 2


rects2()
# 1) Clip anklicken, dann mit Strg Audio und Bild-in-Bild und Effekt dazu
t2.mousePressEvent(Ev(*center(t2._vrects[0]))); t2.mouseReleaseEvent(Ev(0, 0))
assert t2.multi_items() == []
t2.mousePressEvent(Ev(*center(t2._arects[0][1]), CTRL)); t2.mouseReleaseEvent(Ev(0, 0))
assert t2.multi_items() == [("v", 0), ("a", 0)], t2.multi_items()
t2.mousePressEvent(Ev(*center(t2._orects[0][1]), CTRL)); t2.mouseReleaseEvent(Ev(0, 0))
t2.mousePressEvent(Ev(*center(t2._frects[0][1]), CTRL)); t2.mouseReleaseEvent(Ev(0, 0))
assert t2.multi_items() == [("v", 0), ("a", 0), ("o", 0), ("f", 0)], t2.multi_items()
assert t2.multi_changed.calls, "Signal bei Änderung"
# 2) mit Strg wieder abwählen
t2.mousePressEvent(Ev(*center(t2._orects[0][1]), CTRL)); t2.mouseReleaseEvent(Ev(0, 0))
assert t2.multi_items() == [("v", 0), ("a", 0), ("f", 0)], t2.multi_items()
t2.mousePressEvent(Ev(*center(t2._orects[0][1]), CTRL)); t2.mouseReleaseEvent(Ev(0, 0))
# 3) Gruppe ziehen: Audio, Bild-in-Bild und Effekt wandern gemeinsam, der Clip bleibt
before = (p2.audio_clips[0].start, p2.overlays[0].start, p2.fx_span(0))
x0, y0 = center(t2._orects[0][1])
t2.mousePressEvent(Ev(x0, y0)); assert t2._drag and t2._drag["kind"] == "multi", t2._drag
t2.mouseMoveEvent(Ev(x0 + 2.0 * px2, y0)); t2.mouseReleaseEvent(Ev(0, 0))
assert abs(p2.audio_clips[0].start - (before[0] + 2.0)) < 0.01 and abs(p2.overlays[0].start - (before[1] + 2.0)) < 0.01, (p2.audio_clips[0].start, p2.overlays[0].start)
assert abs(p2.fx_span(0)[0] - (before[2][0] + 2.0)) < 0.01 and abs(p2.fx_span(0)[1] - (before[2][1] + 2.0)) < 0.01, p2.fx_span(0)
assert p2.clips[0].in_pt == 0.0 and t2.multi_edited.calls, "Clip bleibt, Signal gesendet"
assert len(t2.multi_items()) == 4, "Auswahl bleibt nach dem Ziehen"
# 4) nach links über 0 hinaus: keiner vor 0, Abstände bleiben
rects2()
x0, y0 = center(t2._orects[0][1])
t2.mousePressEvent(Ev(x0, y0)); t2.mouseMoveEvent(Ev(x0 - 60 * px2, y0)); t2.mouseReleaseEvent(Ev(0, 0))
assert min(p2.audio_clips[0].start, p2.overlays[0].start, p2.fx_span(0)[0]) >= 0.0
assert abs((p2.overlays[0].start - p2.audio_clips[0].start) - (before[1] - before[0])) < 0.01, "Abstand bleibt beim Anstoßen"
# 5) normaler Klick auf einen nicht gewählten Block hebt die Mehrfachauswahl auf
rects2()
t2.mousePressEvent(Ev(*center(t2._arects[1][1]))); t2.mouseReleaseEvent(Ev(0, 0))
assert t2.multi_items() == [] and t2.audio_selected.calls[-1] == (1,), (t2.multi_items(), t2.audio_selected.calls[-1])
# 6) Aufziehrahmen über Audio 0 und Bild-in-Bild 0
rects2()
ra, ro = t2._arects[0][1], t2._orects[0][1]
t2.mousePressEvent(Ev(t2._x(0.3), min(ra.y, ro.y) - 3)); assert t2._drag["kind"] == "band", t2._drag
t2.mouseMoveEvent(Ev(max(ra.x + ra.w, ro.x + ro.w) + 5, max(ra.y + ra.h, ro.y + ro.h) + 3)); t2.mouseReleaseEvent(Ev(0, 0))
got = t2.multi_items()
assert ("a", 0) in got and ("o", 0) in got and ("a", 1) not in got and ("v", 0) in got, got      # der Rahmen quert die Hauptspur
# 7) Rahmen mit Strg ergänzt
t2.mousePressEvent(Ev(t2._x(19.5), t2._lane_y(1) + 3, CTRL))
fr = t2._frects[0][1]
t2.mouseMoveEvent(Ev(fr.x - 4, fr.y - 4)); t2.mouseReleaseEvent(Ev(0, 0))
assert ("f", 0) in t2.multi_items() and ("a", 0) in t2.multi_items(), t2.multi_items()
# 8) Klick ins Leere hebt auf
t2.mousePressEvent(Ev(t2._x(19.5), t2._lane_y(1) + 3)); t2.mouseReleaseEvent(Ev(0, 0))
assert t2.multi_items() == [], t2.multi_items()
# 9) gesperrte Spur wird beim Rahmen übersprungen
t2.set_locked([2])
rects2()
ra = t2._arects[0][1]
t2.mousePressEvent(Ev(t2._x(0.3), ra.y - 4)); t2.mouseMoveEvent(Ev(ra.x + ra.w + 4, ra.y + ra.h + 4)); t2.mouseReleaseEvent(Ev(0, 0))
assert ("a", 0) not in t2.multi_items(), "Audio auf gesperrter Spur nicht wählbar"
t2.set_locked([])
# 10) nur ein Block mit Strg: bleibt Einzelauswahl
t2.clear_multi()
t2._last = None
t2._sel = t2._asel = t2._osel = t2._fsel = -1
t2.mousePressEvent(Ev(*center(t2._orects[0][1]), CTRL)); t2.mouseReleaseEvent(Ev(0, 0))
assert t2.multi_items() == [], "ein einzelner Block ist keine Mehrfachauswahl"
# 11) Anzahl ändert sich: Auswahl verfällt
t2.set_multi([("a", 0), ("o", 0)])
assert len(t2.multi_items()) == 2
p2.overlays.append(OverlayClip("z.mp4", 2.0, start=1.0))
t2.set_project(p2, 0, -1)
assert t2.multi_items() == [], "neue Blöcke: Nummern passen nicht mehr"
print("OK  Mehrfachauswahl: Strg-Klick, Gruppe ziehen, Aufziehrahmen, Sperre")
print("Timeline-Mauslogik OK")
