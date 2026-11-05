"""Stabilisierung: .trf-Ausschnitte, Zwischenspeicher, Filterkette und Wirkung auf ein verwackeltes Video (echtes FFmpeg)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")            # eigener Datenordner, damit der Test nichts Fremdes anfasst
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, stabilize  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


HAS_VS = stabilize.available()
print("vidstab im FFmpeg:", "ja" if HAS_VS else "NEIN (nur die Notlösung wird geprüft)")

# ---------------------------------------------------------------- Stärke → Parameter
s1, z1 = stabilize.strength_params(1)
s100, z100 = stabilize.strength_params(100)
check(s1 < stabilize.strength_params(50)[0] < s100 and z1 < z100 and s100 <= 60 and z100 <= 10, (s1, s100, z1, z100))
print("OK  Stärke")

# ---------------------------------------------------------------- .trf zerschneiden
src = tmp / "x.trf"
src.write_text("VID.STAB 1\n#      accuracy = 9\n" + "".join(f"Frame {i} (List 0 [])\n" for i in range(1, 11)), encoding="utf-8")
dst = tmp / "y.trf"
stabilize.slice_trf(src, dst, 3, 4)
lines = dst.read_text(encoding="utf-8").splitlines()
check(lines[0] == "VID.STAB 1" and lines[2:] == [f"Frame {i} (List 0 [])" for i in range(1, 5)], lines)
check(stabilize.count_frames(dst) == 4, "Bilder zählen")
try:
    stabilize.slice_trf(src, dst, 50, 4)
    check(False, "leerer Ausschnitt")
except stabilize.StabilizeError:
    pass
print("OK  trf zerschneiden")

# ---------------------------------------------------------------- Verwackeltes Video aus einer Rauschfläche
rng = np.random.default_rng(3)
img = Image.new("RGB", (860, 620), (110, 110, 110))
dr = ImageDraw.Draw(img)
for _ in range(140):                                    # Formen mit klaren Kanten: daran erkennt vidstab die Bewegung
    x0, y0 = int(rng.integers(0, 800)), int(rng.integers(0, 560))
    w, h = int(rng.integers(20, 120)), int(rng.integers(20, 100))
    col = tuple(int(v) for v in rng.integers(0, 255, 3))
    (dr.ellipse if rng.random() < 0.4 else dr.rectangle)([x0, y0, x0 + w, y0 + h], fill=col)
bg = tmp / "bg.png"
img.filter(ImageFilter.GaussianBlur(0.8)).save(bg)
shaky = tmp / "shaky.mp4"
sh("-loop", "1", "-framerate", "25", "-i", str(bg), "-t", "4", "-vf",
   "crop=640:360:x='110+34*sin(t*5)':y='120+22*cos(t*6.3)',format=yuv420p", "-c:v", "libx264", "-crf", "10", str(shaky))
info = probe(str(shaky))


def make_project(stab, **kw):
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(shaky), info.duration, has_audio=False, width=info.width, height=info.height, stabilize=stab, **kw)]
    return p


def render(p, name):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True, preview_height=180)
    exporter.run(cmd, total)
    return out


def jitter(video):
    """Mittlerer Unterschied aufeinanderfolgender Bilder (verwackelt = groß, ruhig = klein)."""
    raw = subprocess.run([ff, "-v", "error", "-i", str(video), "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 90, 160).astype(float)
    a = a[:, 12:-12, 20:-20]                           # Ränder weglassen (Zoom/Spiegelung)
    return float(np.abs(np.diff(a, axis=0)).mean())


base = jitter(render(make_project(0), "plain"))

# ohne Analyse: Notlösung deshake (läuft, ändert den Befehl)
p = make_project(60)
cmd, _, _ = exporter.build_command(p, str(tmp / "z.mp4"), draft=True, preview_height=180)
check("deshake" in " ".join(cmd) and "vidstabtransform" not in " ".join(cmd), "ohne Analyse muss deshake benutzt werden")
check(len(stabilize.missing(p)) == (1 if HAS_VS else 0), "Analyse fehlt")
fallback = jitter(render(p, "fallback"))
check(fallback <= base * 1.02, f"deshake sollte nicht schlechter sein ({fallback:.2f} vs {base:.2f})")
print(f"OK  Notlösung deshake: {base:.2f} -> {fallback:.2f}")

if not HAS_VS:
    check(stabilize.missing(p) == [] and stabilize.prepare(p) == 0, "ohne vidstab keine Analyse")
    print("ALLES OK (ohne vidstab)")
    sys.exit(0)

# mit Analyse
prog = []
n = stabilize.prepare(p, on_progress=prog.append)
check(n == 1 and not stabilize.missing(p) and prog and prog[-1] > 0.9, (n, prog[-3:]))
cmd, _, _ = exporter.build_command(p, str(tmp / "z.mp4"), draft=True, preview_height=180)
check("vidstabtransform" in " ".join(cmd), "nach der Analyse muss vidstabtransform benutzt werden")
good = jitter(render(p, "stab"))
check(good < base * 0.45, f"Stabilisierung wirkt zu schwach: {base:.2f} -> {good:.2f}")
check(stabilize.prepare(p) == 0, "zweite Analyse darf nicht nötig sein (Zwischenspeicher)")
print(f"OK  vidstab: {base:.2f} -> {good:.2f}")

# Ausschnitt (wie die Live-Vorschau): bei Text-trf aus der vorhandenen Analyse geschnitten, bei Binär-trf einzeln analysiert
full_trf = stabilize.lookup(str(shaky), 0.0, info.duration)
text_trf = open(full_trf, "rb").read(8).startswith(b"VID.STAB")
print("Analysedatei:", "Text (kann zerschnitten werden)" if text_trf else "Binär (Ausschnitte werden einzeln analysiert)")
before = len(stabilize._load_index())
q = make_project(60)
q.clips[0].in_pt, q.clips[0].out_pt = 1.0, 3.0
if text_trf:
    check(not stabilize.missing(q), "Ausschnitt muss aus der Analyse kommen")
    check(stabilize.prepare(q) == 0, "kein neuer Durchlauf")
else:
    check(len(stabilize.missing(q)) == 1, "Binär-trf lässt sich nicht zerschneiden: Ausschnitt braucht eine eigene Analyse")
    check(stabilize.prepare(q) == 1 and not stabilize.missing(q), "Ausschnitt analysieren")
part = jitter(render(q, "part"))
check(part < base * 0.6, f"Ausschnitt wirkt zu schwach: {base:.2f} -> {part:.2f}")
check(len(stabilize._load_index()) == before + (0 if text_trf else 1), "Index")
check(stabilize.lookup(str(shaky), 1.0, 3.0) is not None, "Ausschnitt wiederfindbar")
print(f"OK  Ausschnitt: {base:.2f} -> {part:.2f}")

# Rückwärts + Tempo + Stabilisierung: Befehl läuft durch
r = make_project(40, reverse=True, speed=2.0)
r.clips[0].in_pt, r.clips[0].out_pt = 0.0, 3.0
stabilize.prepare(r)
render(r, "rev")
# Standbild und Stärke 0 bekommen keinen Filter
check(stabilize.filter_for(make_project(0).clips[0]) == "", "Stärke 0 = aus")
im_clip = make_project(50).clips[0]
im_clip.is_image = True
check(stabilize.filter_for(im_clip) == "", "Bilder werden nicht stabilisiert")
# andere Quelldatei (geändert) → alte Analyse gilt nicht mehr
os.utime(shaky, (1, 1))
check(stabilize.lookup(str(shaky), 0.0, info.duration) is None, "geänderte Datei braucht neue Analyse")
print("OK  Sonderfälle")
print("ALLES OK")
