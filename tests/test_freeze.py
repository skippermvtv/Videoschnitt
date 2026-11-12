"""Standbild einfügen (Freeze-Frame): richtige Stelle, Teilen, Ränder, rückwärts, Einstellungen, echter Export."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import freeze, stillframe  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# 3 s Video: rot 0–1, blau 1–2, grün 2–3, mit Ton
src = tmp / "rgb.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=25:d=1", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=25:d=1",
                "-f", "lavfi", "-i", "color=c=green:s=640x360:r=25:d=1", "-f", "lavfi", "-i", "sine=d=3",
                "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(src)], check=True)


def newproj():
    i = probe(str(src))
    p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
    p.clips = [Clip(str(src), i.duration, has_audio=True, width=i.width, height=i.height)]
    return p


def px(png):
    return np.array(Image.open(png).convert("RGB"))[Image.open(png).size[1] // 2, Image.open(png).size[0] // 2].astype(int)


def near(a, b, tol=45):
    return all(abs(int(x) - y) <= tol for x, y in zip(a, b))


# Stelle finden
p = newproj()
check(freeze.locate(Project(), 1.0) is None, "leeres Projekt")
idx, local = freeze.locate(p, 1.5)
check(idx == 0 and abs(local - 1.5) < 1e-6, (idx, local))
check(abs(freeze.source_time(p.clips[0], 1.5) - 1.5) < 1e-6, "Quellzeit")
c = p.clips[0]
c.speed, c.in_pt = 2.0, 0.5
check(abs(freeze.source_time(c, 0.5) - 1.5) < 1e-6, "Quellzeit mit Tempo und Anfang")
c.speed, c.in_pt, c.reverse = 1.0, 0.0, True
check(abs(freeze.source_time(c, 0.5) - 2.5) < 1e-6, freeze.source_time(c, 0.5))
check(freeze.clamp_seconds(0) == freeze.MIN_SECONDS and freeze.clamp_seconds(99) == freeze.MAX_SECONDS and freeze.clamp_seconds(3) == 3.0, "Sekunden begrenzt")
print("OK  Stelle und Quellzeit")

# Mitten im Clip einfügen: Teilen + Bild
p = newproj()
c0 = p.clips[0]
c0.transition, c0.transition_dur = "fade", 0.5
c0.grade = {"brightness": 0.1}
c0.crop_l = 5.0
png = tmp / "freeze1.png"
freeze.extract(c0, 1.5, str(png))
check(png.is_file() and near(px(png), (0, 0, 255)), f"Bild blau: {px(png)}")
n = freeze.insert(p, 0, 1.5, str(png), 3.0)
check(n == 1 and len(p.clips) == 3, (n, len(p.clips)))
a, img, b = p.clips
check(abs(a.length - 1.5) < 1e-6 and abs(b.length - 1.5) < 1e-6 and abs(img.length - 3.0) < 1e-6, (a.length, img.length, b.length))
check(abs(p.duration - 6.0) < 1e-6, p.duration)
check(img.is_image and not img.has_audio and img.path == str(png) and img.speed == 1.0 and img.transition == "", "Bild-Clip")
check(img.grade == c0.grade and img.crop_l == 5.0, "Bildkorrektur und Zuschnitt übernommen")
check(a.transition == "" and b.transition == "fade", ("Übergang gehört dem letzten Stück", a.transition, b.transition))
check(len({x.uid for x in p.clips}) == 3, "eindeutige Kennungen")
print("OK  einfügen mitten im Clip")

# Ränder
p = newproj()
p.clips[0].transition = "fade"
freeze.insert(p, 0, 0.0, str(png), 2.0)
check(len(p.clips) == 2 and p.clips[0].is_image and not p.clips[1].is_image, "am Anfang davor")
p = newproj()
p.clips[0].transition = "fade"
freeze.insert(p, 0, 3.0, str(png), 2.0)
check(len(p.clips) == 2 and p.clips[1].is_image and p.clips[1].transition == "fade" and p.clips[0].transition == "", "am Ende dahinter, Übergang wandert mit")
print("OK  Ränder")

# Rückwärts: Standbild zeigt die Stelle, die gerade zu sehen war
p = newproj()
p.clips[0].reverse = True                      # läuft grün → blau → rot
freeze.extract(p.clips[0], 1.5, str(tmp / "rev.png"))       # 1,5 s im Clip = Quellzeit 1,5 → blau
check(near(px(tmp / "rev.png"), (0, 0, 255)), px(tmp / "rev.png"))
freeze.extract(p.clips[0], 0.5, str(tmp / "rev2.png"))      # 0,5 s im Clip = Quellzeit 2,5 → grün
check(near(px(tmp / "rev2.png"), (0, 128, 0), 80), px(tmp / "rev2.png"))
freeze.insert(p, 0, 0.5, str(tmp / "rev2.png"), 2.0)
a, img, b = p.clips
check(abs(a.in_pt - 2.5) < 1e-6 and abs(a.out_pt - 3.0) < 1e-6 and abs(b.in_pt - 0.0) < 1e-6 and abs(b.out_pt - 2.5) < 1e-6, (a.in_pt, a.out_pt, b.in_pt, b.out_pt))
print("OK  rückwärts")

# Getrennter Ton
p = newproj()
p.detach_audio(0)
freeze.insert(p, 0, 1.5, str(png), 2.0)
check(not any(a.kind == "video" for a in p.audio_clips) and p.clips[0].has_audio, "Ton wurde vor dem Teilen wieder verbunden")
print("OK  getrennter Ton")

# Echter Export: rot → blau (Standbild 3 s) → grün
p = newproj()
freeze.insert(p, 0, 1.5, str(png), 3.0)
check(abs(p.duration - 6.0) < 1e-6, p.duration)
for t, want in ((0.5, (255, 0, 0)), (2.5, (0, 0, 255)), (4.0, (0, 0, 255)), (5.5, (0, 128, 0))):
    out = tmp / f"fz_{t}.png"
    stillframe.render(p, t, str(out))
    check(near(px(out), want, 80), f"t={t}: {px(out)} erwartet {want}")
from app.core import exporter  # noqa: E402
full = tmp / "full.mp4"
cmd, total, tdir = exporter.build_command(p, str(full))
exporter.run(cmd, total)
d = subprocess.run([paths.find_binary("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", str(full)],
                   capture_output=True, text=True).stdout
durs = {ln.split(",")[0]: float(ln.split(",")[1]) for ln in d.split() if "," in ln}
check(abs(durs.get("video", 0) - 6.0) < 0.2 and abs(durs.get("audio", 0) - 6.0) < 0.3, durs)
print("OK  Export zeigt Standbild an der richtigen Stelle, Länge und Ton stimmen")
print("ALLES OK")
