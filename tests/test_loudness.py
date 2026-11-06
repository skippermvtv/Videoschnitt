"""Lautheit angleichen (loudnorm) und Musik-Ducking: gemessen mit echtem FFmpeg."""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import exporter  # noqa: E402
from app.core.project import AudioClip, Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")
SR = 48000


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def lufs(path):
    """Integrierte Lautheit (EBU R128) und True Peak einer Datei."""
    r = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = r.stderr.split("Summary:")[-1]
    i = float(re.search(r"I:\s+(-?[\d.]+) LUFS", tail).group(1))
    pk = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    return i, float(pk.group(1)) if pk else None


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


def render(pr, name):
    out = tmp / name
    cmd, total, _ = exporter.build_command(pr, str(out), draft=True, preview_height=180)
    exporter.run(cmd, total)
    check(out.exists() and out.stat().st_size > 1000, f"{name} fehlt")
    return out


DUR = 20.0
vid = {}
for nm, amp in (("quiet", 0.03), ("loud", 0.9)):
    f = tmp / f"{nm}.mp4"
    # „Sprache“: Töne mit wechselnder Hülle, damit die Lautheit nicht konstant ist
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x203040:s=320x180:r=25:d={DUR}", "-f", "lavfi", "-i",
                    f"aevalsrc='{amp}*sin(2*PI*300*t)*(0.55+0.45*sin(2*PI*0.7*t))+{amp / 2}*sin(2*PI*1200*t)':d={DUR}:s=48000",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", str(f)], check=True)
    vid[nm] = f


def project_for(src, **kw):
    i = probe(str(src))
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p", **kw)
    p.clips = [Clip(str(src), i.duration, has_audio=True, width=i.width, height=i.height)]
    return p


# ---------------------------------------------------------------- Lautheit angleichen
for nm in ("quiet", "loud"):
    before = lufs(render(project_for(vid[nm]), f"{nm}_off.mp4"))[0]
    after, peak = lufs(render(project_for(vid[nm], normalize=True), f"{nm}_on.mp4"))
    check(abs(after + 14.0) <= 1.5, f"{nm}: {after:.1f} LUFS statt −14 (vorher {before:.1f})")
    check(peak is None or peak <= -0.9, f"{nm}: Spitzenpegel {peak} dBFS über der Grenze")
    print(f"OK  Lautheit {nm}: {before:.1f} → {after:.1f} LUFS, Spitze {peak} dBFS")
check(abs(lufs(tmp / "quiet_off.mp4")[0] + 14.0) > 5.0, "Testquelle muss weit vom Ziel entfernt sein")
for goal in (-16.0, -23.0):
    got, peak = lufs(render(project_for(vid["loud"], normalize=True, lufs_target=goal), f"goal{int(goal)}.mp4"))
    check(abs(got - goal) <= 1.5, f"Ziel {goal}: erreicht {got:.1f} LUFS")
    print(f"OK  Ziel {goal:g} LUFS: erreicht {got:.1f}")
from app.core import audiomix  # noqa: E402
check(audiomix.lufs_goal(Project(lufs_target=float("nan"))) == -14.0 and audiomix.lufs_goal(Project(lufs_target=5)) == -14.0
      and audiomix.lufs_goal(Project(lufs_target="x")) == -14.0 and audiomix.lufs_goal(Project(lufs_target=-23)) == -23.0, "Ziel prüfen")
check(Project.from_json(Project(lufs_target=-16.0, normalize=True).to_json()).lufs_target == -16.0, "Speichern/Laden")
check(Project.from_json('{"normalize": true}').lufs_target == -14.0, "altes Projekt")
check(audiomix.duck_ratio(0) == 1.0 and abs(audiomix.duck_ratio(1) - 20.0) < 1e-9 and audiomix.duck_ratio(0.2) < 2.0 and audiomix.duck_ratio(9) == 20.0, "Duck-Verhältnis")

# ---------------------------------------------------------------- Ducking
speech_src = tmp / "speech.mp4"       # 1 kHz „Sprache“ nur in den ersten 8 s, danach Stille
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x203040:s=320x180:r=25:d=16", "-f", "lavfi", "-i",
                "aevalsrc='if(lt(t,8),0.3*sin(2*PI*1000*t),0)':d=16:s=48000", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-b:a", "256k", str(speech_src)], check=True)
music = tmp / "music.wav"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=16:r=48000,volume=0.3", "-ac", "2", str(music)], check=True)
si = probe(str(speech_src))


def duck_project(**kw):
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p", **kw)
    p.clips = [Clip(str(speech_src), si.duration, has_audio=True, width=si.width, height=si.height)]
    p.audio_clips = [AudioClip(str(music), 16.0, track=2)]
    return p


levels = {}
for name, kw in (("off", {}), ("duck60", {"ducking": True, "ducking_amount": 0.6}), ("duck100", {"ducking": True, "ducking_amount": 1.0}),
                 ("duck20", {"ducking": True, "ducking_amount": 0.2})):
    x = pcm(render(duck_project(**kw), f"duck_{name}.mp4"))
    speaking = x[int(2 * SR):int(7 * SR)]
    silent = x[int(10 * SR):int(15 * SR)]
    levels[name] = (band(speaking, 220), band(silent, 220))
ref_speak, ref_silent = levels["off"]
for name in ("duck60", "duck100", "duck20"):
    sp, si_ = levels[name]
    check(abs(db(si_, ref_silent)) <= 1.5, f"{name}: Musik in den Sprechpausen verändert um {db(si_, ref_silent):+.1f} dB")
red = {n: -db(levels[n][0], ref_speak) for n in ("duck20", "duck60", "duck100")}
check(4.0 <= red["duck20"] <= 9.0 and red["duck60"] >= 10.0, f"Ducking-Stufen unpassend: {red}")
check(red["duck20"] < red["duck60"] <= red["duck100"] + 0.5, f"Stärke wirkt nicht gestaffelt: {red}")
print(f"OK  Ducking: Musik bei Sprache −{red['duck20']:.1f} / −{red['duck60']:.1f} / −{red['duck100']:.1f} dB (20/60/100 %), in den Pausen unverändert")

# Ducking und Angleichen zusammen
pr = duck_project(ducking=True, ducking_amount=0.6, normalize=True)
out = render(pr, "duck_norm.mp4")
check(abs(lufs(out)[0] + 14.0) <= 1.5, f"Ducking + Angleichen: {lufs(out)[0]:.1f} LUFS")
check(abs(probe(str(out)).duration - 16.0) < 0.3, "Länge bleibt erhalten")
print("OK  Ducking + Lautheit zusammen")
print("ALLES OK")
