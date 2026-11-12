"""Drehung für Bild-in-Bild: feste Drehung und Keyframes (echtes FFmpeg, Pixelvergleich der Umrisse)."""
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
from app.core import exporter, overlaykeys  # noqa: E402
from app.core.project import Clip, OverlayClip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


bg = tmp / "bg.mp4"
sh("-f", "lavfi", "-i", "color=c=0x808080:s=640x360:r=25:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(bg))
img = tmp / "white.png"
Image.new("RGB", (200, 100), (255, 255, 255)).save(img)
bi = probe(str(bg))


def make(**kw):
    p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
    p.clips = [Clip(str(bg), bi.duration, has_audio=False, width=bi.width, height=bi.height)]
    o = OverlayClip(str(img), 4.0, 0.0, 4.0, start=0.0, is_image=True, x_pct=50.0, y_pct=50.0, size_pct=30.0, **kw)
    p.overlays = [o]
    return p, o


def frames(p, name, times):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    info = probe(str(out))
    res = []
    for t in times:
        raw = subprocess.run([ff, "-v", "error", "-ss", f"{t}", "-i", str(out), "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, check=True).stdout
        res.append(np.frombuffer(raw, np.uint8).reshape(info.height, info.width).astype(int))
    return res, info.width


def bbox(g, thr=200):
    ys, xs = np.where(g > thr)
    check(len(xs) > 50, "Überlagerung nicht gefunden")
    return xs.max() - xs.min() + 1, ys.max() - ys.min() + 1


def dark_pixels(g):
    return int((g < 90).sum())        # Hintergrund ist grau (128): dunkle Pixel wären ein schwarzer Rand der Drehfläche


# ---- feste Drehung
(g0,), W = frames(make()[0], "r0", [1.0])
w0, h0 = bbox(g0)
check(abs(w0 - W * 0.30) <= 4 and abs(h0 - W * 0.15) <= 4, f"ohne Drehung {w0}x{h0}, W={W}")
(g90,), _ = frames(make(rot=90.0)[0], "r90", [1.0])
w9, h9 = bbox(g90)
check(abs(w9 - h0) <= 5 and abs(h9 - w0) <= 5, f"90°: {w9}x{h9}, erwartet {h0}x{w0}")
check(dark_pixels(g90) == 0, f"90°: schwarzer Rand ({dark_pixels(g90)} Pixel)")
(g45,), _ = frames(make(rot=45.0)[0], "r45", [1.0])
w4, h4 = bbox(g45)
exp45 = (w0 + h0) / (2 ** 0.5)
check(abs(w4 - exp45) <= 6 and abs(h4 - exp45) <= 6, f"45°: {w4}x{h4}, erwartet {exp45:.0f}")
check(dark_pixels(g45) == 0, "45°: kein schwarzer Rand")
(gm,), _ = frames(make(rot=-90.0)[0], "rm90", [1.0])
check(abs(bbox(gm)[0] - h0) <= 5, "−90° wie 90°")
print("OK  feste Drehung")

# ---- Keyframes: 0° → 90° über 4 s; Größe bleibt gleich
p, o = make()
o.keys = [dict(t=0.0, x=50, y=50, size=30, opacity=100, rot=0.0), dict(t=1.0, x=50, y=50, size=30, opacity=100, rot=90.0)]
o.anim_ease = False
check(overlaykeys.active(o), "Keyframes aktiv")
(ga, gb, gc), W = frames(p, "rk", [0.2, 2.0, 3.8])
wa, ha = bbox(ga)
wb, hb = bbox(gb)
wc, hc = bbox(gc)
import math


def expect(deg):
    r = math.radians(deg)
    return w0 * abs(math.cos(r)) + h0 * abs(math.sin(r)), w0 * abs(math.sin(r)) + h0 * abs(math.cos(r))


for (bw_, bh_), deg, label in (((wa, ha), 4.5, "Anfang"), ((wb, hb), 45.0, "Mitte"), ((wc, hc), 85.5, "Ende")):
    ew, eh = expect(deg)
    check(abs(bw_ - ew) <= 9 and abs(bh_ - eh) <= 9, f"{label} ({deg}°): {bw_}x{bh_}, erwartet {ew:.0f}x{eh:.0f}")
check(all(dark_pixels(g) == 0 for g in (ga, gb, gc)), "Keyframes: kein schwarzer Rand")
print("OK  Keyframe-Drehung, Größe bleibt")

# ---- Drehung zusammen mit wachsender Größe und Rand
p, o = make(border=True)
o.keys = [dict(t=0.0, x=50, y=50, size=20, opacity=100, rot=0.0), dict(t=1.0, x=50, y=50, size=40, opacity=100, rot=0.0)]
o.anim_ease = False
(g1, g2), W = frames(p, "grow", [0.2, 3.8])
p, o = make(border=True)
o.keys = [dict(t=0.0, x=50, y=50, size=20, opacity=100, rot=0.0), dict(t=1.0, x=50, y=50, size=40, opacity=100, rot=360.0)]
o.anim_ease = False
(r1, r2), W = frames(p, "growrot", [0.2, 3.8])
bw1, _ = bbox(g1, 200)
bw2, bh2 = bbox(g2, 200)
check(bw2 > bw1 * 1.5, f"Größe wächst ohne Drehung: {bw1} → {bw2}")
# Ende: 95 % von 360° = −18°; erwartet wird der Umriss des (gleich großen) Rechtecks bei diesem Winkel
rw2, rh2 = bbox(r2, 200)
ang = math.radians(18.0)
ew, eh = bw2 * math.cos(ang) + bh2 * math.sin(ang), bw2 * math.sin(ang) + bh2 * math.cos(ang)
check(abs(rw2 - ew) <= 10 and abs(rh2 - eh) <= 10, f"Größe bei Drehung und Wachstum: {rw2}x{rh2}, erwartet {ew:.0f}x{eh:.0f}")
check(dark_pixels(r1) == 0 and dark_pixels(r2) == 0, "Wachstum + Drehung: kein schwarzer Rand")
print("OK  Drehung mit Größe und Rand")

# ---- Vorlagen, Daten
p, o = make()
for name in ("spin_in", "wobble"):
    check(name in overlaykeys.PRESETS and overlaykeys.apply_preset(name, o) and overlaykeys.active(o), name)
    check(all("rot" in k for k in o.keys), f"{name}: rot in jedem Punkt")
overlaykeys.apply_preset("spin_in", o)
check(o.keys[0]["rot"] == -360.0 and o.keys[0]["opacity"] == 0.0 and o.keys[-1]["rot"] == 0.0, o.keys)
o.rot = 20.0
overlaykeys.apply_preset("wobble", o)
check(o.keys[0]["rot"] == 20.0 and min(k["rot"] for k in o.keys) == 10.0 and max(k["rot"] for k in o.keys) == 30.0, "wobble um die feste Drehung")
c = overlaykeys.clean([{"t": 0, "rot": 9999}, {"t": 1, "rot": -9999}], o)
check([k["rot"] for k in c] == [720.0, -720.0], c)
c = overlaykeys.clean([{"t": 0}, {"t": 1}], o)
check(all(k["rot"] == 20.0 for k in c), "fehlendes rot kommt aus dem festen Wert")
# Speichern/Laden
p2 = Project.from_json(p.to_json())
check(p2.overlays[0].rot == 20.0 and p2.overlays[0].keys == o.keys, "Speichern/Laden")
d = json.loads(p.to_json())
d["overlays"][0].pop("rot")
check(Project.from_json(json.dumps(d)).overlays[0].rot == 0.0, "altes Projekt")
print("OK  Vorlagen und Daten")
print("ALLES OK")
