"""Standbild als PNG: richtige Stelle, volle Format-Größe, Logo und Text sind dabei, Projekt bleibt unverändert."""
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
from app.core import stillframe  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def solid(name, color, dur=2):
    f = tmp / name
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=25:d={dur}", "-f", "lavfi", "-i", "sine=d=%d" % dur,
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(f)], check=True)
    return f


def clip_of(path):
    i = probe(str(path))
    return Clip(str(path), i.duration, has_audio=True, width=i.width, height=i.height)


red, blue = solid("still_red.mp4", "red"), solid("still_blue.mp4", "blue")
p = Project(format_id="youtube_16_9", export_id="youtube_1080p", layout="fill")
p.clips = [clip_of(red), clip_of(blue)]
before = p.to_json()

check(stillframe.clamp_time(p, -3) == 0.0 and abs(stillframe.clamp_time(p, 99) - (p.duration - 0.1)) < 1e-9, "Zeit begrenzt")
check(stillframe.default_name(p, 75.4).startswith("Standbild_") and stillframe.default_name(p, 3.2) == "Standbild_00-03.png", stillframe.default_name(p, 3.2))

for t, want in ((0.5, (255, 0, 0)), (3.0, (0, 0, 255))):
    out = tmp / f"s_{t}.png"
    stillframe.render(p, t, str(out))
    im = Image.open(out).convert("RGB")
    check(im.size == (1920, 1080), f"Größe {im.size}")
    px = np.array(im)[540, 960].astype(int)
    check(all(abs(int(a) - b) <= 40 for a, b in zip(px, want)), f"t={t}: Farbe {px}, erwartet {want}")
print("OK  richtige Stelle, volle Größe")
check(p.to_json() == before, "Projekt bleibt unverändert")

# Logo ist im Bild
logo = tmp / "logo.png"
Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(logo)
p.watermark, p.wm_corner, p.wm_size, p.wm_opacity = str(logo), "br", 20.0, 100.0
out = tmp / "logo.png.out.png"
stillframe.render(p, 0.5, str(out))
a = np.array(Image.open(out).convert("RGB")).astype(int)
check(a[1080 - 70, 1920 - 100].min() > 200, f"Logo unten rechts fehlt: {a[1080 - 70, 1920 - 100]}")
check(a[40, 40][0] > 200 and a[40, 40][1] < 60, "Rest des Bildes bleibt rot")
print("OK  mit Logo")

try:
    stillframe.render(Project(), 0.0, str(tmp / "x.png"))
except Exception as e:
    check("keine Clips" in str(e), str(e))
else:
    check(False, "leeres Projekt muss Fehler geben")
print("OK  leeres Projekt")
print("ALLES OK")
