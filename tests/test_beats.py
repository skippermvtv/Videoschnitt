"""Beat-Erkennung (künstliche Takte mit bekannten Schlagzeiten) und Schnitt auf den Beat (echte Projekte)."""
import os
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import beats, markers  # noqa: E402
from app.core.project import AudioClip, Clip, Project  # noqa: E402

SR = 22050
rng = np.random.default_rng(7)


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def kick(n):
    t = np.arange(int(0.12 * SR)) / SR
    return (np.sin(2 * np.pi * (60 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 25) * 0.9)[:n]


def hat(n):
    d = int(0.03 * SR)
    return (rng.standard_normal(d) * np.exp(-np.arange(d) / (0.008 * SR)) * 0.25)[:n]


def make(name, bpm, secs, offset=0.0, hats=False, noise=0.0, swing=0.0):
    x = np.zeros(int(secs * SR) + SR)
    period = 60.0 / bpm
    truth = []
    t = offset
    while t < secs - 0.2:
        i = int(t * SR)
        k = kick(len(x) - i)
        x[i:i + len(k)] += k
        truth.append(t)
        if hats:
            j = int((t + period / 2 + swing) * SR)
            h = hat(len(x) - j)
            x[j:j + len(h)] += h
        t += period
    x += rng.standard_normal(len(x)) * noise
    x = np.clip(x, -1, 1)
    path = tmp / f"{name}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes((x * 32000).astype(np.int16).tobytes())
    return str(path), truth


def run(name, bpm, secs=20.0, tol_bpm=0.015, tol_t=0.045, **kw):
    path, truth = make(name, bpm, secs, **kw)
    clip = AudioClip(path, secs)
    res = beats.analyze_audio(clip)
    check(abs(res.bpm - bpm) / bpm <= tol_bpm, f"{name}: {res.bpm} BPM statt {bpm}")
    miss = [min(abs(b - t) for b in res.beats) for t in truth if 0.2 < t < secs - 0.5]      # ganz am Rand fehlt Umgebung für die Analyse
    worst = max(miss)
    check(worst <= tol_t, f"{name}: größte Abweichung {worst * 1000:.0f} ms")
    check(res.reliable, f"{name}: Stärke {res.strength}")
    print(f"OK  {name}: {res.bpm} BPM (Soll {bpm}), größte Abweichung {worst * 1000:.0f} ms, Stärke {res.strength}")
    return res, truth


run("klick120", 120)
run("kick128_offset", 128, offset=0.31)
run("kick90", 90, offset=0.12)
run("kick100_hats", 100, hats=True, offset=0.2)
run("kick140_rauschen", 140, noise=0.03, offset=0.05)
run("kick75_hats_swing", 75, hats=True, swing=0.03, offset=0.4)

# nicht ganze Länge: nur ein Abschnitt (in_pt/out_pt) und Tempo des Blocks
path, truth = make("abschnitt", 110, 30.0, offset=0.1)
clip = AudioClip(path, 30.0, in_pt=10.0, out_pt=22.0, start=5.0)
res = beats.analyze_audio(clip)
tl = beats.to_project_times(clip, res)
exp = [5.0 + (t - 10.0) for t in truth if 10.0 <= t <= 22.0]
check(all(min(abs(a - b) for b in tl) < 0.05 for a in exp[1:-1]), "Abschnitt: Zeiten auf der Timeline")
clip.speed = 2.0                                    # doppelt so schnell: Schläge liegen halb so weit auseinander
tl2 = beats.to_project_times(clip, res)
check(abs((tl2[1] - tl2[0]) - (tl[1] - tl[0]) / 2) < 0.01, "Tempo des Blocks wird berücksichtigt")
check(len(beats.to_project_times(clip, res, step=4)) == (len(res.beats) + 3) // 4, "jeder 4. Schlag")
check(beats.to_project_times(clip, res, step=2, offset=1)[0] == tl2[1], "Versatz")
print("OK  Abschnitt, Tempo des Blocks, jeder n-te")

# Fehlerfälle
silent = tmp / "still.wav"
with wave.open(str(silent), "wb") as w:
    w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
    w.writeframes(np.zeros(SR * 6, np.int16).tobytes())
for bad, word in ((AudioClip(str(silent), 6.0), "keine Schläge"), (AudioClip(path, 30.0, in_pt=0.0, out_pt=1.0), "zu kurz"),
                  (AudioClip(path, 30.0, reverse=True), "rückwärts"), (AudioClip(str(tmp / "gibtsnicht.wav"), 10.0), "kein Ton")):
    try:
        beats.analyze_audio(bad)
    except beats.BeatError as e:
        check(word in str(e), f"Meldung '{e}' soll '{word}' enthalten")
    else:
        check(False, f"BeatError erwartet ({word})")
noise_only = tmp / "rauschen.wav"
with wave.open(str(noise_only), "wb") as w:
    w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
    w.writeframes((rng.standard_normal(SR * 12) * 3000).astype(np.int16).tobytes())
res = beats.analyze_audio(AudioClip(str(noise_only), 12.0))
check(not res.reliable, f"Rauschen darf nicht als sicherer Rhythmus gelten (Stärke {res.strength})")
check("schwach" in beats.describe(res), "Hinweis bei schwachem Rhythmus")
print("OK  Fehlerfälle und schwacher Rhythmus")

# ---- Schnitt auf den Beat
def proj(transition=False):
    p = Project()
    p.clips = [Clip("a.mp4", 20.0, 0.0, 3.3, has_audio=True), Clip("b.mp4", 20.0, 1.0, 5.1, has_audio=True),
               Clip("c.mp4", 20.0, 0.0, 2.9, has_audio=True), Clip("d.mp4", 3.0, 0.0, 3.0, has_audio=True)]
    if transition:
        p.clips[0].transition, p.clips[0].transition_dur = "fade", 0.4
        p.clips[2].transition, p.clips[2].transition_dur = "fade", 0.3
    return p


grid = [round(0.5 * k, 3) for k in range(1, 40)]               # 120 BPM: Beats alle 0,5 s
p = proj()
ch, sk = beats.snap_clips(p, grid)
starts = [p.clip_start(i) for i in range(len(p.clips))]
check(all(any(abs(s - g) < 1e-3 for g in grid) for s in starts[1:]), f"Schnitte auf dem Raster: {starts}")
check(abs(starts[1] - 3.5) < 1e-6 and abs(starts[2] - 7.5) < 1e-6, f"nächster Beat: {starts}")
check(ch >= 2, f"geändert {ch}")
check(p.clips[3].out_pt <= 3.0 + 1e-9, "Quelle ist kurz: Clip wird nicht über das Ende verlängert")
check(any(abs(p.duration - g) < 1e-3 for g in grid), f"Ende liegt auch auf einem Beat: {p.duration}")
check(abs(p.clips[1].in_pt - 1.0) < 1e-9, "Anfang des Quellstücks bleibt")
print("OK  Schnitt auf den Beat", [round(s, 2) for s in starts], "Ende", round(p.duration, 2))

p = proj(transition=True)
beats.snap_clips(p, grid)
starts = [p.clip_start(i) for i in range(len(p.clips))]
check(all(any(abs(s - g) < 5e-3 for g in grid) for s in starts[1:]), f"mit Übergängen: {starts}")
print("OK  mit Übergängen", [round(s, 3) for s in starts])

# jeder 2. Beat, Tempo des Clips, Tempokurve überspringen, getrennter Ton folgt
p = proj()
p.clips[1].speed = 2.0
p.clips[2].ramp_id = "r1"
p.detach_audio(0)
p.detach_audio(1)
len_c2 = p.clips[2].length
ch, sk = beats.snap_clips(p, grid[1::2])                       # 1,0 / 2,0 / 3,0 …
st = [p.clip_start(i) for i in range(len(p.clips))]
check(abs(st[1] - 3.0) < 1e-6, f"jeder 2. Beat: {st}")
check(abs(p.clips[2].length - len_c2) < 1e-9 and sk >= 1, "Tempokurve unverändert und übersprungen")
check(abs(p.clips[1].length - (p.clip_start(2) - st[1] + p.overlap_after(1))) < 1e-6, "Länge mit Tempo 2")
link = {a.link: a.start for a in p.audio_clips if a.kind == "video"}
check(abs(link[p.clips[1].uid] - st[1]) < 1e-6, "getrennter Ton folgt dem Clip")
print("OK  Tempo, Tempokurve, getrennter Ton")

try:
    beats.snap_clips(proj(), [1.0])
except beats.BeatError:
    pass
else:
    check(False, "zu wenige Beats")

# Marker aus Beats
p = proj()
n = markers.add_many(p, beats.to_project_times(AudioClip(path, 30.0, start=0.0), beats.BeatResult(120.0, [0.5 * k for k in range(8)], 3.0), step=2))
check(n == 4 and markers.times(p) == [0.0, 1.0, 2.0, 3.0], markers.times(p))
print("OK  Marker aus Beats")
print("ALLES OK")
