"""Chroma-Key-Vorschau: Standbild des Clips mit Key über dem Hintergrund."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import keypreview  # noqa: E402
from app.core.project import Clip, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def run(args):
    subprocess.run([ff, "-v", "error", "-y", *args], check=True)


fg = tmp / "fg.mp4"
run(["-f", "lavfi", "-i", "color=c=0x00ff00:s=320x180:r=25:d=4", "-vf", "drawbox=x=40:y=60:w=60:h=60:color=0xff0000:t=fill",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(fg)])
bg = tmp / "bg.png"
Image.new("RGB", (640, 360), (0, 0, 255)).save(bg)
info = probe(str(fg))


def near(px, rgb, tol=60):
    return all(abs(a - b) <= tol for a, b in zip(px, rgb))


c = Clip(str(fg), info.duration, has_audio=False, width=info.width, height=info.height)
c.key_color, c.key_bg = "#00ff00", str(bg)
png = tmp / "prev.png"
keypreview.render(c, str(png), height=270)
im = Image.open(png).convert("RGB")
w, h = im.size
check(h == 270 and w == 480, f"Größe {w}x{h}")
check(near(im.getpixel((int(w * 0.8), int(h * 0.2))), (0, 0, 255)), "Grün ist durch Blau ersetzt")
check(near(im.getpixel((int(w * 70 / 320), int(h * 90 / 180))), (255, 0, 0)), "Motiv bleibt")
check(c.in_pt == 0.0 and c.out_pt == info.duration and c.key_color == "#00ff00", "der Clip selbst bleibt unverändert")
print("OK  Vorschau mit Hintergrund")

# Zeitpunkt wählen, Ausschnitt des Clips, Tempo/Übergang stören nicht
c2 = Clip(str(fg), info.duration, in_pt=1.0, out_pt=3.0, speed=2.0, transition="fade", transition_dur=0.5, has_audio=False,
          width=info.width, height=info.height)
c2.key_color = "#00ff00"
keypreview.render(c2, str(tmp / "p2.png"), at=0.5)
im2 = Image.open(tmp / "p2.png").convert("RGB")
check(near(im2.getpixel((int(im2.size[0] * 0.8), int(im2.size[1] * 0.2))), (0, 0, 0)), "ohne Hintergrund: schwarz")
print("OK  Zeitpunkt, Tempo, ohne Hintergrund")

# Standbild als Clip
still = tmp / "still.png"
Image.new("RGB", (320, 180), (0, 255, 0)).save(still)
c3 = Clip(str(still), 5.0, is_image=True, has_audio=False, width=320, height=180)
c3.out_pt = 5.0
c3.key_color, c3.key_bg = "#00ff00", str(bg)
keypreview.render(c3, str(tmp / "p3.png"), height=180)
im3 = Image.open(tmp / "p3.png").convert("RGB")
check(near(im3.getpixel((im3.size[0] // 2, im3.size[1] // 2)), (0, 0, 255)), "Standbild mit Key")
print("OK  Standbild")
print("ALLES OK")
