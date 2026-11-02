"""Prüft die Python-Logik des Hauptfensters OHNE echtes Qt (Attrappen-Module).

Findet Tippfehler, falsche Namen und Logikfehler. Ersetzt NICHT den echten Start-Test
(tests/ui_smoke.py mit PySide6) – der läuft zusätzlich auf GitHub.
"""
import sys, types, subprocess, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.paths import find_binary  # noqa: E402

FFMPEG = find_binary("ffmpeg")      # mitgeliefertes FFmpeg bzw. PATH (auf dem Build-Server liegt es nur in vendor/)


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
    def __sub__(self, o): return 0
    def __add__(self, o): return 0
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
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=5",
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
win.add_effect_block("glitch", 1.0)                      # Effekt-Block auf der FX-Spur anlegen
win.add_effect_block("vhs", 0.0)
assert len(win.project.effects) == 2 and win.fsel == 1
win.project.effects[0]["intensity"] = 80
win.project.fx_set_span(0, 0.0, 3.0)
print("Effekte:", win.project.effects)
assert win.project.effects[0]["end"] == 3.0 or win.project.fx_span(0)[1] == 3.0
# Text
win.add_text(); t0 = win.project.texts[0]; t0.text = "Test äöü"; t0.font = ""; t0.start = 0.0; t0.end = 2.0; t0.size_pct = 7.0
# Export-Befehl bauen und ausführen
from app.core import exporter
cmd, total, t = exporter.build_command(win.project, str(tmp / "o.mp4"))
exporter.run(cmd, total)
print("Export ok, Dauer", round(total, 2))
# Audio: trennen, Musik hinzufügen, verbinden, löschen
aud = tmp / "m.wav"
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=2", str(aud)], check=True)
win.sel = 0
win.detach_selected_audio()
assert win.project.clips[0].audio_detached and len(win.project.audio_clips) == 1 and win.asel == 0
win.detach_selected_audio()                       # zweites Mal: nichts passiert
assert len(win.project.audio_clips) == 1
win.add_audio_files([str(aud)], track=2)
assert len(win.project.audio_clips) == 2 and win.project.audio_clips[1].track == 2 and win.asel == 1
win.import_files([str(aud)])                      # reine Audiodatei per Import -> Musik
assert len(win.project.audio_clips) == 3
win.fsel = -1; win.asel = 2; win.delete_selected(); assert len(win.project.audio_clips) == 2
win.reattach_selected_clip()
assert not win.project.clips[0].audio_detached and len(win.project.audio_clips) == 1
win.sel = 0; win.move_clip(1)
win.sel = 1; win.delete_clip()                    # Clip löschen entfernt auch den getrennten Ton
win.sel = 0; win.detach_selected_audio(); win.sel = 0; win.delete_clip()
assert all(a.kind != "video" for a in win.project.audio_clips)
win.add_audio_files([str(tmp / "gibtsnicht.mp3")])  # Fehlerpfad (Dialog ist Attrappe)
win._add_to_timeline(str(vid)); win.sel = 0
# Rückgängig/Wiederholen, Umsortieren, Springen, Sicherung
win.project.clips = win.project.clips[:1]; win._refresh_timeline(select=0)
win._history.reset(win.project.to_json())
n = len(win.project.clips)
win._add_to_timeline(str(vid))
win._history.observe(win.project.to_json(), 100.0); win._history.observe(win.project.to_json(), 101.0)
win.undo(); assert len(win.project.clips) == n, len(win.project.clips)
win.redo(); assert len(win.project.clips) == n + 1
first = win.project.clips[0].uid
win._reorder_clip(0, 1); assert win.project.clips[1].uid == first
win._open_media = lambda *a, **k: None
win._seek_project(0.5); assert win.sel == 0
win._seek_project(999.0); assert win.sel == len(win.project.clips) - 1
win.project.clips[0].out_pt = 1.0; win._on_clip_edited(0)
assert win.autosave_now() and win._autosave_path().exists()
dur = len(win.project.clips)
win.project.clips = []; assert win.restore_autosave() and len(win.project.clips) == dur
assert not win._autosave_path().exists()
# Standbild + Bild-in-Bild
img = tmp / "b.png"
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=200x100", "-frames:v", "1", str(img)], check=True)
win.import_files([str(img)])
assert win.media[str(img)].is_image
nclips = len(win.project.clips)
win._add_to_timeline(str(img))
assert win.project.clips[-1].is_image and win.project.clips[-1].length == 5.0 and len(win.project.clips) == nclips + 1
win.add_overlay_files([str(img), str(vid)])
assert len(win.project.overlays) == 2 and win.project.overlays[0].is_image and not win.project.overlays[1].is_image
assert win.osel == 1
win._select_overlay(0); assert win.osel == 0 and win.asel == -1
win.delete_selected(); assert len(win.project.overlays) == 1 and win.osel == -1
win._select_clip(0); assert win.osel == -1
cmd, total, _t = exporter.build_command(win.project, str(tmp / "o2.mp4"), draft=True)
exporter.run(cmd, total)
print("Standbild/Overlay ok")
# Untertitel
win.project.subtitles = []
win.add_subtitle(); win.add_subtitle()
assert len(win.project.subtitles) == 2
win.sub_list.currentRow = lambda: 0
win.remove_subtitle(); assert len(win.project.subtitles) == 1
srt = tmp / "u.srt"
srt.write_text("1\n00:00:00,500 --> 00:00:02,000\nHallo\n\n2\n00:00:02,500 --> 00:00:04,000\nWelt\n", encoding="utf-8")
assert win.load_srt(str(srt)) == 2 and win.project.subtitles[1].text == "Welt"
win.project.sub_style.anim = "fade"
cmd, total, _t = exporter.build_command(win.project, str(tmp / "o3.mp4"), draft=True)
exporter.run(cmd, total)
win._on_asr_done([mw.SubtitleCue(0, 1, "x")], ""); assert len(win.project.subtitles) == 1
win._on_asr_done(None, "Fehler"); assert len(win.project.subtitles) == 1
win.clear_subtitles(); assert not win.project.subtitles
print("Untertitel ok")
# Bewegung / Transform
win.sel = 0
win.add_keyframe(); win.add_keyframe()
c0 = win.project.clips[0]
assert len(c0.keyframes) == 2 and c0.keyframes[1]["t"] == 0.25
win.kf_list.currentRow = lambda: 0
win.remove_keyframe(); assert len(c0.keyframes) == 1
win.cmb_motion.currentData = lambda: "ken_burns"
win._on_motion_preset(1); assert len(c0.keyframes) == 2 and c0.keyframes[1]["zoom"] == 135
win._rotate_clip(90); win._rotate_clip(90); assert c0.rotate == 180
win.apply_motion_to_all(); assert all(len(c.keyframes) == 2 for c in win.project.clips)
cmd, total, _t = exporter.build_command(win.project, str(tmp / "o4.mp4"), draft=True)
exporter.run(cmd, total)
win.reset_transform(); assert c0.rotate == 0
win.clear_motion(); assert c0.keyframes == []
print("Bewegung ok")
# Vorschau mit Zwischenspeicher und Export mit Rückfall
import os as _os
_os.environ["APPDATA"] = str(tmp / "appdata")
calls = []
def fake_job(cmd, total, title, on_done):
    calls.append(title); exporter.run(cmd, total); on_done("")
win._run_job = fake_job
win.project.clips[0].keyframes = []
win.render_preview(); assert len(calls) == 1, calls
from app.core import preview as _pc
assert any(_pc.cache_dir().glob("*.mp4")) and win._preview_path
win.render_preview(); assert len(calls) == 1, "zweite Vorschau muss aus dem Zwischenspeicher kommen"
win._on_perf_changed()
outs = []
def fail_then_ok(cmd, total, title, on_done):
    outs.append("-c:v h264_nvenc" in " ".join(cmd) or "libx264" in " ".join(cmd))
    on_done("boom" if len(outs) == 1 else "")
win._run_job = fail_then_ok
exporter.hw_encoder = lambda: None
win._start_export(str(tmp / "hw_out.mp4"), False)
print("Vorschau/Export ok")
# Hilfe-Fenster
win._text_dialog("Kurzanleitung", html="<b>x</b>"); win._text_dialog("Lizenzen", plain="x")
print("Hilfe ok")
# 1.1: Diagnose-Fenster, Fehlerdialog (ohne Dialoge), Spracherkennung einrichten (bereits eingerichtet -> nur Hinweis)
import os as _os
_os.environ["CLIPFORGE_NO_PROMPTS"] = "1"
win._report_dialog("Diagnose", "x")
win.show_crash("Traceback test")
print("Diagnose ok")
# Projekt speichern/laden
win.project.save(str(tmp / "p.cforge")); p2 = Project.load(str(tmp / "p.cforge"))
assert len(p2.clips) == len(win.project.clips) and p2.effects == win.project.effects
print("UI-Logik OK")
