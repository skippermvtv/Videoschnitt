"""Wasserzeichen/Logo: Ecke, Größe und Deckkraft per Pixelvergleich (16:9, 9:16, 1:1), Speichern/Laden, Fehler."""
import json
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
from app.core import exporter, multiexport as mx  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# schwarzes Video, weißes Logo (2:1) – so ist der Helligkeitswert direkt die Deckkraft
src = tmp / "black.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:size=640x360:rate=25:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
logo = tmp / "logo.png"
Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(logo)
info = probe(str(src))


def make(fmt, export, **kw):
    p = Project(format_id=fmt, export_id=export, layout="fill")
    p.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height)]
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def frame(p, name):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out))
    exporter.run(cmd, total)
    i = probe(str(out))
    raw = subprocess.run([ff, "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(i.height, i.width).astype(float), i.width, i.height


def level(op):                      # Weiß auf Schwarz im begrenzten Bereich (16…235)
    return 16 + (235 - 16) * op


for fmt, exp in (("youtube_16_9", "youtube_1080p"), ("shorts", "vertical_1080"), ("insta_square", "square_1080")):
    # ohne Logo: alles dunkel
    g, W, H = frame(make(fmt, exp), f"plain_{fmt}")
    check(g.max() < 25, f"{fmt}: ohne Logo muss alles dunkel sein (max {g.max()})")
    ow = int(W * 0.20) // 2 * 2
    oh = ow // 2
    m = max(4, int(W * 0.025))
    for corner in ("tl", "tr", "bl", "br"):
        g, W, H = frame(make(fmt, exp, watermark=str(logo), wm_corner=corner, wm_size=20.0, wm_opacity=100.0), f"{fmt}_{corner}")
        x0 = m if corner in ("tl", "bl") else W - ow - m
        y0 = m if corner in ("tl", "tr") else H - oh - m
        inside = g[y0 + 4:y0 + oh - 4, x0 + 4:x0 + ow - 4]
        check(inside.min() > 225, f"{fmt}/{corner}: Logo nicht in der Ecke (min {inside.min()})")
        mask = np.ones_like(g, bool)
        mask[max(0, y0 - 3):y0 + oh + 3, max(0, x0 - 3):x0 + ow + 3] = False
        check(g[mask].max() < 25, f"{fmt}/{corner}: außerhalb des Logos muss dunkel bleiben (max {g[mask].max()})")
        # Größe: helle Spalten/Zeilen zählen
        bright = g > 120
        cols = int(bright.any(axis=0).sum())
        rows = int(bright.any(axis=1).sum())
        check(abs(cols - ow) <= 3 and abs(rows - oh) <= 3, f"{fmt}/{corner}: Größe {cols}x{rows}, erwartet {ow}x{oh}")
    # Deckkraft
    g, W, H = frame(make(fmt, exp, watermark=str(logo), wm_corner="br", wm_size=20.0, wm_opacity=50.0), f"{fmt}_op")
    x0, y0 = W - ow - m, H - oh - m
    v = g[y0 + 6:y0 + oh - 6, x0 + 6:x0 + ow - 6].mean()
    check(abs(v - level(0.5)) < 8, f"{fmt}: Deckkraft 50 % ergibt {v:.1f}, erwartet {level(0.5):.1f}")
    print(f"OK  {fmt}: vier Ecken, Größe, Deckkraft ({W}x{H})")

# Mehrere Formate: Logo gilt in jeder Kopie
p = make("youtube_16_9", "youtube_1080p", watermark=str(logo), wm_corner="tl", wm_size=20.0, wm_opacity=100.0)
out_dir = tmp / "out"
out_dir.mkdir(exist_ok=True)
for j in mx.plan(p, ["youtube_16_9", "shorts"], out_dir, "Film"):
    check(j.project.watermark == str(logo) and j.project.wm_corner == "tl", "Logo-Einstellungen in der Kopie")
    cmd, total, _ = exporter.build_command(j.project, j.out)
    exporter.run(cmd, total)
    i = probe(j.out)
    raw = subprocess.run([ff, "-v", "error", "-ss", "1", "-i", j.out, "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    g = np.frombuffer(raw, np.uint8).reshape(i.height, i.width)
    m = max(4, int(i.width * 0.025))
    check(g[m + 6:m + 20, m + 6:m + 40].min() > 225, f"{j.format_id}: Logo oben links fehlt")
print("OK  Mehrere Formate")

# Speichern / Laden / altes Projekt
p = make("youtube_16_9", "youtube_1080p", watermark=str(logo), wm_corner="bl", wm_size=9.0, wm_opacity=40.0)
f = tmp / "p.json"
p.save(str(f))
q = Project.load(str(f))
check((q.watermark, q.wm_corner, q.wm_size, q.wm_opacity) == (str(logo), "bl", 9.0, 40.0), "Laden")
d = json.loads(p.to_json())
for k in ("watermark", "wm_corner", "wm_size", "wm_opacity"):
    d.pop(k, None)
old = Project.from_json(json.dumps(d))
check(old.watermark == "" and old.wm_corner == "br" and old.wm_size == 14.0 and old.wm_opacity == 80.0, "altes Projekt")
print("OK  Speichern/Laden")

# Fehler
for bad, word in ((str(tmp / "gibtsnicht.png"), "nicht gefunden"), (str(src), "Bilddatei")):
    try:
        cmd, total, _ = exporter.build_command(make("youtube_16_9", "youtube_1080p", watermark=bad), str(tmp / "x.mp4"))
    except exporter.ExportError as e:
        check(word in str(e), f"Meldung: {e}")
    else:
        check(False, f"ExportError erwartet für {bad}")
print("OK  Fehlermeldungen")
print("ALLES OK")
