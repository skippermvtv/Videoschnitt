"""Pipette: Umrechnung der Mausposition, Mittelwert und der ganze Weg (Standbild → Farbe → Greenscreen im Export)."""
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
from app.core import colorpick as cp, exporter, frames  # noqa: E402
from app.core.project import Clip, OverlayClip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# ---------------------------------------------------------------- Umrechnung
# Anzeige 1000×400, Bild 1600×900 → Bild 711×400, links/rechts je ~144 Rand
check(cp.map_click(500, 200, 1000, 400, 1600, 900) == (800, 450), cp.map_click(500, 200, 1000, 400, 1600, 900))
check(cp.map_click(10, 200, 1000, 400, 1600, 900) is None and cp.map_click(990, 200, 1000, 400, 1600, 900) is None, "Ränder sind kein Bild")
x0 = (1000 - 400 * 16 / 9) / 2
check(cp.map_click(x0 + 0.1, 0.1, 1000, 400, 1600, 900) == (0, 0), "linke obere Ecke")
check(cp.map_click(1000 - x0 - 0.1, 399.9, 1000, 400, 1600, 900) == (1599, 899), "rechte untere Ecke")
check(cp.map_click(5, 5, 0, 400, 100, 100) is None and cp.map_click(5, 5, 100, 100, 0, 0) is None, "ungültige Größen")
# Hochformat-Bild in breiter Anzeige
check(cp.map_click(500, 200, 1000, 400, 900, 1600) == (450, 800), "Hochformat mittig")
print("OK  Umrechnung")

# ---------------------------------------------------------------- Nachbarschaft und Mittelwert
nb = cp.neighborhood(0, 0, 100, 100)
check(len(nb) == 9 and (0, 0) in nb and (2, 2) in nb, nb)
check(len(cp.neighborhood(50, 50, 100, 100)) == 25 and len(cp.neighborhood(99, 99, 100, 100, 1)) == 4, "Rand/Mitte")
check(cp.average_hex([(255, 0, 0), (0, 0, 255)]) == "#800080" and cp.average_hex([]) == "#000000" and cp.average_hex([(10, 20, 30)]) == "#0a141e", "Mittelwert")
print("OK  Nachbarschaft und Mittelwert")

# ---------------------------------------------------------------- Ganzer Weg
KEY = "2ecc40"       # kein reines Grün, wie bei echter Greenscreen-Folie
ov = tmp / "gs.mp4"   # links Folie (leicht verrauscht), rechts rotes Objekt
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x{KEY}:s=320x360:r=25:d=3", "-f", "lavfi", "-i", "color=c=red:s=320x360:r=25:d=3",
                "-filter_complex", "[0:v]noise=alls=6:allf=t[a];[a][1:v]hstack,format=yuv444p", "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv444p", str(ov)], check=True)
png = tmp / "pick.png"
frames.extract_frame(str(ov), str(png), 1.0)
im = Image.open(png).convert("RGB")
W, H = im.size
check((W, H) == (640, 360), im.size)
# Klick in die Mitte der linken Hälfte (Anzeige 800×450, Bild 640×360 → Faktor 1,25)
ix, iy = cp.map_click(200 * 1.25, 225, 800, 450, W, H)
col = cp.average_hex([im.getpixel(p) for p in cp.neighborhood(ix, iy, W, H)])
r, g, b = (int(col[i:i + 2], 16) for i in (1, 3, 5))
check(abs(r - 0x2e) <= 14 and abs(g - 0xcc) <= 14 and abs(b - 0x40) <= 14, f"gewählte Farbe {col} statt #{KEY}")
ix, iy = cp.map_click(600 * 1.25, 225, 800, 450, W, H)
colr = cp.average_hex([im.getpixel(p) for p in cp.neighborhood(ix, iy, W, H)])
check(int(colr[1:3], 16) > 200 and int(colr[3:5], 16) < 50, f"rechts rot: {colr}")
print(f"OK  Standbild → Farbe: {col}")

base = tmp / "base.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=640x360:r=25:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)], check=True)
bi, oi = probe(str(base)), probe(str(ov))
pr = Project(format_id="youtube_16_9", export_id="youtube_1080p")
pr.clips = [Clip(str(base), bi.duration, has_audio=False, width=bi.width, height=bi.height)]
pr.overlays = [OverlayClip(str(ov), oi.duration, 0.0, oi.duration, start=0.0, x_pct=50.0, y_pct=50.0, size_pct=100.0,
                           key_color=col, key_similarity=30.0, key_blend=10.0, key_spill=True)]
out = tmp / "keyed.mp4"
cmd, total, _ = exporter.build_command(pr, str(out), draft=True, preview_height=360)
exporter.run(cmd, total)
shot = tmp / "keyed.png"
subprocess.run([ff, "-v", "error", "-y", "-ss", "1.0", "-i", str(out), "-frames:v", "1", str(shot)], check=True)
k = np.array(Image.open(shot).convert("RGB")).astype(int)
h, w = k.shape[:2]
left, right = k[h // 2, w // 4], k[h // 2, 3 * w // 4]
check(all(abs(int(a) - 128) <= 25 for a in left), f"Folie nicht entfernt: links {tuple(left)} (erwartet Grau)")
check(right[0] > 200 and right[1] < 60, f"Objekt muss bleiben: rechts {tuple(right)}")
print("OK  mit der gewählten Farbe verschwindet die Folie im Export")
print("ALLES OK")
