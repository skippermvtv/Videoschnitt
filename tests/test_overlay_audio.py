"""Ton von Bild-in-Bild: Schalter, Lautstärke, Tempo, Start, Ducking, Dateien ohne Ton, Fenster-Projekt (echtes FFmpeg)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import exporter, window as projwin  # noqa: E402
from app.core.project import AudioClip, Clip, OverlayClip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")
SR = 48000


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def pcm(path):
    r = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)


def band(x, f, w=20.0):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / len(x) * 4
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    m = (fr > f - w) & (fr < f + w)
    return float(np.sqrt(np.sum(spec[m] ** 2))) + 1e-12


def db(a, b):
    return 20 * np.log10(a / b)


def seg(x, a, b):
    return x[int(a * SR):int(b * SR)]


def make(name, size, dur, audio=None, color="0x336699"):
    f = tmp / name
    cmd = [ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=25:d={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", audio, "-shortest", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(f)]
    subprocess.run(cmd, check=True)
    return f


main_v = make("main.mp4", "320x180", 12)                                        # ohne Ton
ov_v = make("ov.mp4", "320x180", 6, "aevalsrc=0.4*sin(2*PI*880*t):d=6:s=48000")        # mit Ton, 880 Hz
ov_silent = make("ov_silent.mp4", "320x180", 6, color="0x993333")               # ohne Tonspur
mi = probe(str(main_v))
oi = probe(str(ov_v))
check(oi.has_audio and not probe(str(ov_silent)).has_audio, "Testdateien")


def project(**ov_kw):
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(main_v), mi.duration, has_audio=False, width=mi.width, height=mi.height)]
    p.overlays = [OverlayClip(str(ov_v), oi.duration, 0.0, oi.duration, start=2.0, **ov_kw)]
    return p


def render(p, name):
    out = tmp / name
    cmd, total, _ = exporter.build_command(p, str(out), draft=True, preview_height=180)
    exporter.run(cmd, total)
    check(out.exists() and out.stat().st_size > 1000, f"{name} fehlt")
    return out


# Aus (Standard): kein Ton, wie bisher
off = pcm(render(project(), "off.mp4"))
check(band(seg(off, 3, 7), 880) < 0.005, f"Standard muss stumm bleiben ({band(seg(off, 3, 7), 880):.4f})")
# An: Ton erscheint zur Startzeit und nur während des Blocks
on_path = render(project(sound=True), "on.mp4")
on = pcm(on_path)
lvl = band(seg(on, 3, 7), 880)
check(lvl > 0.03, f"Ton von Bild-in-Bild fehlt (Pegel {lvl:.3f})")
check(band(seg(on, 0.2, 1.6), 880) < 0.005 and band(seg(on, 8.5, 11.5), 880) < 0.005, "Ton nur während des Blocks (2–8 s)")
check(abs(len(on) / SR - 12.0) < 0.3, f"Länge {len(on) / SR:.2f} s")
print(f"OK  Ton an/aus, Startzeit (Pegel {lvl:.2f})")
# Lautstärke 50 % → −6 dB
half = pcm(render(project(sound=True, volume=50.0), "half.mp4"))
check(abs(db(band(seg(half, 3, 7), 880), lvl) + 6.0) < 1.0, f"50 %: {db(band(seg(half, 3, 7), 880), lvl):+.1f} dB")
check(band(seg(pcm(render(project(sound=True, volume=0.0), "zero.mp4")), 3, 7), 880) < 0.005, "Lautstärke 0 = stumm")
# Tempo 2: Block dauert nur 3 s (2–5 s), Ton eine Oktave höher entfällt durch atempo → Tonhöhe bleibt, Dauer halbiert
fast = pcm(render(project(sound=True, speed=2.0), "fast.mp4"))
check(band(seg(fast, 2.5, 4.5), 880) > 0.03 and band(seg(fast, 6, 9), 880) < 0.005, "Tempo 2: Ton endet nach 3 s")
print("OK  Lautstärke, Tempo")
# Einblenden: am Anfang leiser als in der Mitte
fd = pcm(render(project(sound=True, fade_in=1.5), "fade.mp4"))
check(band(seg(fd, 2.0, 2.4), 880) < 0.5 * band(seg(fd, 4.5, 5.5), 880), "Einblenden wirkt nicht")
print("OK  Einblenden")

# Datei ohne Tonspur, Standbild: Schalter an, aber kein Absturz und kein Ton
p = project(sound=True)
p.overlays[0] = OverlayClip(str(ov_silent), 6.0, 0.0, 6.0, start=2.0, sound=True)
out = render(p, "silent.mp4")
check(abs(probe(str(out)).duration - 12.0) < 0.3, "Export mit tonloser Datei")
img = tmp / "i.png"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", str(img)], check=True)
p = project()
p.overlays[0] = OverlayClip(str(img), 10.0, 0.0, 4.0, start=1.0, is_image=True, sound=True)
render(p, "image.mp4")
print("OK  ohne Tonspur / Standbild")

# Ducking: Musik (220 Hz) wird leiser, solange der Bild-in-Bild-Ton läuft
music = tmp / "music.wav"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc=0.3*sin(2*PI*220*t):d=12:s=48000", "-ac", "2", str(music)], check=True)


def with_music(**kw):
    p = project(sound=True)
    p.audio_clips = [AudioClip(str(music), 12.0, track=2)]
    for k, v in kw.items():
        setattr(p, k, v)
    return p


plain = pcm(render(with_music(), "m_plain.mp4"))
duck = pcm(render(with_music(ducking=True, ducking_amount=0.8), "m_duck.mp4"))
check(db(band(seg(duck, 3, 7), 220), band(seg(plain, 3, 7), 220)) < -6.0, "Musik wird bei Bild-in-Bild-Ton nicht leiser")
check(abs(db(band(seg(duck, 9.5, 11.5), 220), band(seg(plain, 9.5, 11.5), 220))) < 1.5, "Musik nach dem Block unverändert")
check(band(seg(plain, 3, 7), 880) > 0.03 and band(seg(plain, 3, 7), 220) > 0.03, "Musik und Bild-in-Bild-Ton zusammen")
print("OK  Ducking reagiert auf den Bild-in-Bild-Ton")

# Mit Hauptton und Lautheit angleichen
p = with_music(normalize=True)
out = render(p, "m_norm.mp4")
check(abs(probe(str(out)).duration - 12.0) < 0.3, "Länge mit Lautheit")

# Fenster-Projekt der Live-Vorschau (Anfang des Blocks abgeschnitten): Ton läuft weiter
p = project(sound=True)
wp, off_t, wl = projwin.project_window(p, 4.0, 4.0)
check(wp.overlays and wp.overlays[0].sound and wp.overlays[0].in_pt > 1.5, "Fenster: Block angeschnitten und Ton-Schalter erhalten")
win_pcm = pcm(render(wp, "window.mp4"))
check(band(seg(win_pcm, 0.3, wl - 0.3), 880) > 0.03, "Fenster: Ton fehlt")
print("OK  Live-Vorschau-Fenster")

# Speichern / Laden / altes Projekt
q = Project.from_json(project(sound=True, volume=70.0).to_json())
check(q.overlays[0].sound and q.overlays[0].volume == 70.0, "Speichern/Laden")
old = Project.from_json('{"overlays":[{"path":"a.mp4","duration":3.0}]}')
check(old.overlays[0].sound is False and old.overlays[0].volume == 100.0, "altes Projekt bleibt stumm")
print("OK  Speichern/Laden")
print("ALLES OK")
