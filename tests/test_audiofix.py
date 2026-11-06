"""Ton verbessern: Rauschen entfernen / Sprache klarer (echtes FFmpeg, gemessen an verrauschten Testtönen)."""
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
from app.core import audiofix, exporter  # noqa: E402
from app.core.project import AudioClip, Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")
SR = 48000


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def pcm(path):
    r = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)


def rms(x):
    return float(np.sqrt(np.mean(x * x))) + 1e-12


def band(x, f, w=15.0):
    """Pegel (RMS) um die Frequenz f herum."""
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / len(x) * 4
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    m = (fr > f - w) & (fr < f + w)
    return float(np.sqrt(np.sum(spec[m] ** 2))) + 1e-12


def db(a, b):
    return 20 * np.log10(a / b)


# ---------------------------------------------------------------- Filterkette
check(audiofix.chain(0, 0) == "" and audiofix.chain() == "", "ohne Einstellung keine Kette")
check(audiofix.chain(50, 0).startswith("afftdn=") and "highpass" not in audiofix.chain(50, 0), audiofix.chain(50, 0))
check("highpass" in audiofix.chain(0, 50) and "equalizer" in audiofix.chain(0, 50) and "afftdn" not in audiofix.chain(0, 50), audiofix.chain(0, 50))
check(audiofix.chain(500, -3) == audiofix.chain(100, 0), "Werte werden begrenzt")
check(audiofix.chain("x", None) == "", "kaputte Werte")
nr1, _ = audiofix.denoise_params(1)
nr2, _ = audiofix.denoise_params(100)
check(0 < nr1 < nr2 <= 40, (nr1, nr2))
check("nf=-45" in audiofix.chain(50, 0) and "nf=-30" in audiofix.chain(50, 0, -30) and "nf=-80" in audiofix.chain(50, 0, -200), "Rauschpegel")
print("OK  Filterkette")

# ---------------------------------------------------------------- Quellen
noisy = tmp / "noisy.wav"           # 0–3 s nur Rauschen, ab 3 s zusätzlich 440 Hz
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=8:c=white:a=0.08:r=48000:seed=7", "-f", "lavfi",
                "-i", "sine=f=440:d=8:r=48000,volume='if(gte(t,3),0.3,0)':eval=frame", "-filter_complex",
                "[0:a][1:a]amix=inputs=2:duration=first:normalize=0", "-ac", "2", str(noisy)], check=True)
rumble = tmp / "rumble.wav"         # 50 Hz Brummen + 3 kHz „Sprache“
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=50:d=4:r=48000,volume=0.3", "-f", "lavfi",
                "-i", "sine=f=3000:d=4:r=48000,volume=0.1", "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0",
                "-ac", "2", str(rumble)], check=True)
vid = tmp / "v.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x203040:s=320x180:r=25:d=8", "-i", str(noisy), "-shortest",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)
vinfo = probe(str(vid))


def render(project, name):
    out = tmp / name
    cmd, total, _ = exporter.build_command(project, str(out), draft=True, preview_height=180)
    exporter.run(cmd, total)
    check(out.exists() and out.stat().st_size > 1000, f"{name} fehlt")
    return pcm(out)


def clip_project(src, info, **kw):
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height, **kw)]
    return p


# ---------------------------------------------------------------- Rauschpegel messen
quiet = tmp / "quiet.wav"           # gleiche Quelle, aber viel leiseres Rauschen (−50 dB)
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=8:c=white:a=0.005:r=48000:seed=7", "-f", "lavfi",
                "-i", "sine=f=440:d=8:r=48000,volume='if(gte(t,3),0.3,0)':eval=frame", "-filter_complex",
                "[0:a][1:a]amix=inputs=2:duration=first:normalize=0", "-ac", "2", str(quiet)], check=True)
f_loud, f_quiet = audiofix.noise_floor(str(noisy)), audiofix.noise_floor(str(quiet))
check(-33 <= f_loud <= -24, f"lautes Rauschen gemessen als {f_loud} dB (erwartet etwa −27)")
check(-55 <= f_quiet <= -47, f"leises Rauschen gemessen als {f_quiet} dB (erwartet etwa −51)")
check(audiofix.noise_floor(str(tmp / "gibt-es-nicht.wav")) == audiofix.DEFAULT_FLOOR, "fehlende Datei → Standardwert")
print(f"OK  Rauschpegel gemessen: {f_loud} dB und {f_quiet} dB")

# ---------------------------------------------------------------- Rauschen entfernen (Videoclip)
base = render(clip_project(vid, vinfo), "base.mp4")
dn = render(clip_project(vid, vinfo, denoise=70), "dn.mp4")
seg = slice(int(1.5 * SR), int(2.8 * SR))              # nur Rauschen
n0, n1 = rms(base[seg]), rms(dn[seg])
check(db(n0, n1) >= 6.0, f"Rauschen nur um {db(n0, n1):.1f} dB gesenkt")
tone = slice(int(5.0 * SR), int(7.0 * SR))
t0, t1 = band(base[tone], 440), band(dn[tone], 440)
check(abs(db(t1, t0)) <= 3.0, f"Ton (440 Hz) verändert sich um {db(t1, t0):.1f} dB – soll erhalten bleiben")
check(db(t1, n1 * 1.0) > 6.0, "Nutzton muss deutlich über dem Restrauschen liegen")
print(f"OK  Rauschen entfernen: {db(n0, n1):.1f} dB weniger, 440 Hz {db(t1, t0):+.1f} dB")

# ---------------------------------------------------------------- Rauschen entfernen (Audioblock)
p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
p.clips = [Clip(str(vid), vinfo.duration, has_audio=False, width=vinfo.width, height=vinfo.height)]
p.audio_clips = [AudioClip(str(noisy), 8.0, track=1, denoise=70)]
ab = render(p, "ab_dn.mp4")
p.audio_clips = [AudioClip(str(noisy), 8.0, track=1)]
ab0 = render(p, "ab0.mp4")
check(db(rms(ab0[seg]), rms(ab[seg])) >= 6.0, f"Audioblock: Rauschen nur um {db(rms(ab0[seg]), rms(ab[seg])):.1f} dB gesenkt")
qs = Project(format_id="youtube_16_9", export_id="youtube_1080p")
qs.clips = list(p.clips)
qs.audio_clips = [AudioClip(str(quiet), 8.0, track=1)]
q0 = render(qs, "q0.mp4")
qs.audio_clips = [AudioClip(str(quiet), 8.0, track=1, denoise=70)]
q1 = render(qs, "q1.mp4")
check(db(rms(q0[seg]), rms(q1[seg])) >= 6.0, f"leises Rauschen nur um {db(rms(q0[seg]), rms(q1[seg])):.1f} dB gesenkt")
check(abs(db(band(q1[tone], 440), band(q0[tone], 440))) <= 3.0, "Nutzton bei leisem Rauschen erhalten")
print("OK  Rauschen entfernen (Audioblock, laut und leise)")

# ---------------------------------------------------------------- Sprache klarer
rv = tmp / "rv.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x203040:s=320x180:r=25:d=4", "-i", str(rumble), "-shortest",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(rv)], check=True)
rinfo = probe(str(rv))
b0 = render(clip_project(rv, rinfo), "rv0.mp4")
b1 = render(clip_project(rv, rinfo, voice=100), "rv1.mp4")
seg2 = slice(int(1.0 * SR), int(3.0 * SR))
low = db(band(b1[seg2], 50), band(b0[seg2], 50))
high = db(band(b1[seg2], 3000), band(b0[seg2], 3000))
check(low <= -9.0, f"Brummen (50 Hz) nur um {low:.1f} dB gesenkt")
check(3.0 <= high <= 8.0, f"3 kHz um {high:+.1f} dB – erwartet etwa +6")
# schwache Stärke wirkt schwächer
b2 = render(clip_project(rv, rinfo, voice=20), "rv2.mp4")
low2 = db(band(b2[seg2], 50), band(b0[seg2], 50))
check(low2 > low, f"Stärke 20 muss weniger wirken als 100 ({low2:.1f} vs {low:.1f})")
print(f"OK  Sprache klarer: 50 Hz {low:.1f} dB, 3 kHz {high:+.1f} dB")

# ---------------------------------------------------------------- Zusammenspiel mit Tempo / Rückwärts / Länge
q = clip_project(vid, vinfo, denoise=40, voice=40, speed=2.0)
sp = render(q, "speed.mp4")
check(abs(len(sp) / SR - 4.0) < 0.3, f"Länge mit Tempo 2: {len(sp) / SR:.2f} s")
q = clip_project(vid, vinfo, denoise=40, voice=40)
q.clips[0].reverse = True
rev = render(q, "rev.mp4")
check(abs(len(rev) / SR - 8.0) < 0.3 and rms(rev) > 0.01, "Rückwärts mit Tonverbesserung")
print("OK  mit Tempo / Rückwärts")

# ---------------------------------------------------------------- Speichern / Laden / Ton trennen
p = clip_project(vid, vinfo, denoise=35, voice=15)
q = Project.from_json(p.to_json())
check(q.clips[0].denoise == 35 and q.clips[0].voice == 15, "Speichern/Laden")
old = Project.from_json('{"clips":[{"path":"a.mp4","duration":3.0}],"audio_clips":[{"path":"a.wav","duration":2.0}]}')
check(old.clips[0].denoise == 0 and old.audio_clips[0].voice == 0, "alte Projekte ohne die Felder")
a = p.detach_audio(0)
check(a is not None and a.denoise == 35 and a.voice == 15, "Ton trennen nimmt die Einstellung mit")
a.denoise, a.voice = 10, 90
p.reattach_audio(0)
check(p.clips[0].denoise == 10 and p.clips[0].voice == 90, "Ton verbinden bringt sie zurück")
print("OK  Speichern, Laden, Trennen")
print("ALLES OK")
