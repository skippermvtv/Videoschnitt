"""Masken im Vorschaubild: Geometrie des Rahmens (ohne Qt) und Einzelbild aus dem Projekt (echtes FFmpeg)."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import frames, maskgeom  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# ---------------------------------------------------------------- Geometrie
m = {"shape": "rect", "x": 50.0, "y": 50.0, "w": 40.0, "h": 20.0}
check(maskgeom.box(m) == (30.0, 40.0, 70.0, 60.0), maskgeom.box(m))
W, H = 1000.0, 500.0
# Ecken (300|200 … 700|300 in Bildpunkten), Ränder, Mitte, daneben
check(maskgeom.hit(m, W, H, 300, 200) == "tl", "Ecke oben links")
check(maskgeom.hit(m, W, H, 700, 300) == "br", "Ecke unten rechts")
check(maskgeom.hit(m, W, H, 700, 200) == "tr" and maskgeom.hit(m, W, H, 300, 300) == "bl", "Ecken rechts oben / links unten")
check(maskgeom.hit(m, W, H, 500, 200) == "t" and maskgeom.hit(m, W, H, 500, 300) == "b", "Ränder oben/unten")
check(maskgeom.hit(m, W, H, 300, 250) == "l" and maskgeom.hit(m, W, H, 700, 250) == "r", "Ränder links/rechts")
check(maskgeom.hit(m, W, H, 500, 250) == "move", "Mitte")
check(maskgeom.hit(m, W, H, 50, 50) is None and maskgeom.hit(m, 0, 0, 1, 1) is None, "daneben")

# Verschieben: begrenzt auf das Bild
a = maskgeom.drag(m, "move", 10.0, -5.0)
check((a["x"], a["y"]) == (60.0, 45.0) and (a["w"], a["h"]) == (40.0, 20.0), a)
a = maskgeom.drag(m, "move", 80.0, 80.0)
check((a["x"], a["y"]) == (100.0, 100.0), a)
# Größe: rechter Rand +10 → Breite 50, Mitte wandert um 5 mit; Ecke links oben −10/−10
a = maskgeom.drag(m, "r", 10.0, 0.0)
check(abs(a["w"] - 50.0) < 1e-9 and abs(a["x"] - 55.0) < 1e-9 and a["h"] == 20.0, a)
a = maskgeom.drag(m, "tl", -10.0, -10.0)
check(abs(a["w"] - 50.0) < 1e-9 and abs(a["h"] - 30.0) < 1e-9 and abs(a["x"] - 45.0) < 1e-9 and abs(a["y"] - 45.0) < 1e-9, a)
# nicht kleiner als das Minimum und nicht "umklappen"
a = maskgeom.drag(m, "r", -500.0, 0.0)
check(abs(a["w"] - maskgeom.MIN_SIZE) < 1e-9 and a["x"] < 100, a)
a = maskgeom.drag(m, "t", 0.0, 500.0)
check(abs(a["h"] - maskgeom.MIN_SIZE) < 1e-9, a)
# Ziehen ist immer vom Start-Zustand aus gerechnet (kein Aufsummieren)
b = maskgeom.drag(m, "r", 4.0, 0.0)
check(b["w"] == 44.0 and m["w"] == 40.0, "Eingabe darf nicht verändert werden")
check(maskgeom.cursor_name("tl") == "size_fdiag" and maskgeom.cursor_name(None) == "arrow" and maskgeom.cursor_name("move") == "size_all", "Zeiger")
x, y, w, h = maskgeom.fit_rect(1000, 400, 1920, 1080)
check(abs(w / h - 1920 / 1080) < 1e-6 and y == 0.0 and x > 0 and h == 400.0, (x, y, w, h))
x, y, w, h = maskgeom.fit_rect(400, 1000, 1920, 1080)
check(x == 0.0 and w == 400.0 and y > 0, (x, y, w, h))
print("OK  Geometrie")

# ---------------------------------------------------------------- Einzelbild
src = tmp / "t.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=3", "-f", "lavfi",
                "-i", "sine=duration=3", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
info = probe(str(src))
p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
p.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height)]
# Mit schwarzem Masken-Effekt in der Mitte: das Einzelbild für den Rahmen muss OHNE Effekt entstehen
p.effects = [{"id": "mask_black", "intensity": 100, "start": 0.0, "end": None,
              "mask": {"shape": "rect", "x": 50, "y": 50, "w": 60, "h": 60, "feather": 0}}]
png = tmp / "f.png"
frames.frame_at(p, 1.0, 180, str(png), str(tmp))
check(png.exists() and png.stat().st_size > 0, "Einzelbild fehlt")
im = np.array(Image.open(png).convert("L")).astype(float)
hh, ww = im.shape
check(abs(ww / hh - 16 / 9) < 0.05, f"Seitenverhältnis {ww}x{hh}")
center = im[hh // 2 - 10: hh // 2 + 10, ww // 2 - 10: ww // 2 + 10]
check(center.std() > 5 or center.mean() > 40, f"Mitte ist schwarz – Effekt wurde nicht entfernt (Mittel {center.mean():.1f})")
check(len(p.effects) == 1, "Das Projekt darf nicht verändert werden")
print("OK  Einzelbild ohne Effekt", im.shape)
print("ALLES OK")
