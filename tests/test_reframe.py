"""Auto-Hochkant: Kamerafahrt, Keyframes, Export im Layout „Füllen“ (echter FFmpeg) – ein heller Block wandert von links nach rechts."""
import copy
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, frames, pieces, reframe, speedramp  # noqa: E402
from app.core import window as projwin  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
rng = np.random.default_rng(11)


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# ---------------------------------------------------------------- Rechnen
c0 = Clip("x.mp4", 10.0, width=1920, height=1080)
check(abs(reframe.window_fraction(c0, 9 / 16) - (9 / 16) / (16 / 9)) < 1e-9, reframe.window_fraction(c0, 9 / 16))
check(reframe.applicable(c0, 9 / 16) == "", reframe.applicable(c0, 9 / 16))
check("Standbild" in reframe.applicable(Clip("a.png", 5.0, is_image=True, width=1920, height=1080), 9 / 16), "Bild")
check(reframe.applicable(Clip("v.mp4", 5.0, width=1080, height=1920), 9 / 16) != "", "Hochformat-Quelle")
c90 = Clip("x.mp4", 10.0, width=1920, height=1080, rotate=90)
check(reframe.applicable(c90, 9 / 16) != "", "gedrehter Clip ist schon hochkant")
ccrop = Clip("x.mp4", 10.0, width=1920, height=1080, crop_l=25.0, crop_r=25.0)
check(abs(reframe.visible_aspect(ccrop) - 960 / 1080) < 1e-9, reframe.visible_aspect(ccrop))

# Fenster findet die laute Stelle; ohne Inhalt: Mitte
sc = np.zeros((3, 100), dtype=np.float32)
sc[0, 70:76] = 1.0
sc[1, 10:16] = 1.0
cen = reframe.best_centers(sc, 0.3)
check(abs(cen[0] - 0.73) < 0.2 and abs(cen[1] - 0.13) < 0.2 and cen[2] == 0.5, cen)

# Kamerafahrt: Totzone, begrenzte Geschwindigkeit, Grenzen
path = reframe.camera_path([0.5] * 10 + [0.55] * 10, 0.3, 5.0, "normal")
check(max(path) - min(path) < 1e-9 and abs(path[0] - 0.5) < 1e-9, "kleine Abweichung bleibt in der Totzone")
path = reframe.camera_path([0.2] * 5 + [0.8] * 40, 0.3, 5.0, "normal")
step = max(abs(b - a) for a, b in zip(path, path[1:]))
check(step <= reframe.STYLES["normal"][1] / 5.0 + 1e-9, f"zu schnell: {step}")
check(min(path) >= 0.15 - 1e-9 and max(path) <= 0.85 + 1e-9 and path[-1] > 0.6, (min(path), max(path), path[-1]))
fast = reframe.camera_path([0.2] * 5 + [0.8] * 40, 0.3, 5.0, "lebhaft")
calm = reframe.camera_path([0.2] * 5 + [0.8] * 40, 0.3, 5.0, "ruhig")
check(fast[12] > calm[12], "lebhaft folgt schneller als ruhig")

# Keyframes
keys = reframe.to_keys([0.15 + 0.7 * i / 49 for i in range(50)], 0.3)
check(2 <= len(keys) <= reframe.MAX_KEYS and keys[0]["t"] == 0.0 and keys[-1]["t"] == 1.0, keys)
check(keys[0]["x"] < -95 and keys[-1]["x"] > 95, keys)
rev = reframe.to_keys([0.15 + 0.7 * i / 49 for i in range(50)], 0.3, reverse=True)
check(rev[0]["x"] > 95 and rev[-1]["x"] < -95, "rückwärts spiegelt die Fahrt")
many = reframe.to_keys([0.5 + 0.3 * np.sin(i / 2.0) for i in range(400)], 0.3)
check(len(many) <= reframe.MAX_KEYS, len(many))
print("OK  Rechnen")

# ---------------------------------------------------------------- Teilen / Fenster / Tempokurve verteilen die Keyframes
def fresh():
    c = Clip("x.mp4", 10.0, width=1920, height=1080, has_audio=False)
    c.reframe = [{"t": 0.0, "x": -100.0}, {"t": 1.0, "x": 100.0}]
    return c


cl = fresh()
proj = Project(format_id="shorts", export_id="fast_draft", layout="fill")
proj.clips = [cl]
pieces.split_into(proj, 0, [(0.0, 4.0), (6.0, 10.0)])
a, b = proj.clips[0].reframe, proj.clips[1].reframe
check(abs(a[0]["x"] + 100) < 1e-6 and abs(a[-1]["x"] - (-20)) < 1.0, a)
check(abs(b[0]["x"] - 20) < 1.0 and abs(b[-1]["x"] - 100) < 1e-6, b)
check(all(set(k) == {"t", "x"} for k in a + b), a)
p2 = Project(format_id="shorts", export_id="fast_draft", layout="fill")
p2.clips = [fresh()]
wp, delta, wl = projwin.project_window(p2, 5.0, 2.0)
w0 = wp.clips[0].reframe
check(abs(w0[0]["x"] - 0.0) < 2.0 and abs(w0[-1]["x"] - 40.0) < 2.0, w0)
p3 = Project(format_id="shorts", export_id="fast_draft", layout="fill")
p3.clips = [fresh()]
speedramp.apply(p3, 0, [[0, 1.0], [50, 2.0], [100, 1.0]])
check(len(p3.clips) > 1 and all(len(c.reframe) >= 2 for c in p3.clips), [c.reframe for c in p3.clips])
check(p3.clips[0].reframe[0]["x"] == -100.0 and p3.clips[-1].reframe[-1]["x"] == 100.0, "Tempokurve verteilt die Fahrt")
speedramp.merge_group(p3, 0)
check(len(p3.clips) == 1 and p3.clips[0].reframe == fresh().reframe, p3.clips[0].reframe)
# JSON
p4 = Project(format_id="shorts", export_id="fast_draft", layout="fill")
p4.clips = [fresh()]
p5 = Project.from_json(p4.to_json())
check(p5.clips[0].reframe == fresh().reframe, p5.clips[0].reframe)
print("OK  Teilen, Fenster, Tempokurve, Speichern")

# ---------------------------------------------------------------- Echt: Block wandert von links nach rechts
W, H, FPS, SEC = 640, 360, 10, 8
n = FPS * SEC
bgimg = rng.integers(60, 120, (H, W)).astype(np.uint8)
raw = bytearray()
for i in range(n):
    u = i / (n - 1)
    cx = int(60 + u * (W - 120))
    fr = bgimg.copy()
    fr[110:250, cx - 30:cx + 30] = 250
    raw += fr.tobytes()
src = tmp / "reframe_move.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(src)], input=bytes(raw), check=True)
info = probe(str(src))
p = Project(format_id="shorts", export_id="fast_draft", layout="fit")
p.clips = [Clip(str(src), info.duration, has_audio=False, width=info.width, height=info.height)]
prog = []
res, notes = reframe.analyze_project(p, [0], "normal", on_progress=prog.append)
keys = res[0]
check(not notes and len(keys) >= 2 and prog and prog[-1] == 1.0, (notes, keys))
check(keys[0]["x"] < -30 and keys[-1]["x"] > 30, f"Fahrt folgt dem Block nicht: {keys}")
check(all(b["x"] >= a["x"] - 1e-6 for a, b in zip(keys, keys[1:])), f"Fahrt geht nicht gleichmäßig nach rechts: {keys}")
check(reframe.apply(p, res) == 1 and p.layout == "fill" and p.clips[0].reframe == keys, "apply")
cmd, total, tw = exporter.build_command(p, str(tmp / "reframe_out.mp4"), draft=True)
check("crop=" in " ".join(cmd) and "(iw-" in " ".join(cmd), "Ausdruck im Filtergraph")
exporter.run(cmd, total)
out = tmp / "reframe_out.mp4"
oi = probe(str(out))
check(oi.width < oi.height, (oi.width, oi.height))
g = frames.read_gray(str(out), 2.0, oi.width, oi.height)
# Der helle Block liegt im Ausschnitt: in jedem Bild ein heller Streifen, nie ganz am Rand abgeschnitten
bright = [(f > 200).sum() for f in g]
check(min(bright) > 0.04 * g[0].size, f"Block verlässt den Ausschnitt: {bright}")
# ohne Reframe (Mitte): am Anfang und Ende ist der Block nicht zu sehen
p_mid = copy.deepcopy(p)
p_mid.clips[0].reframe = []
cmd, total, _ = exporter.build_command(p_mid, str(tmp / "reframe_mid.mp4"), draft=True)
exporter.run(cmd, total)
gm = frames.read_gray(str(tmp / "reframe_mid.mp4"), 2.0, oi.width, oi.height)
bm = [(f > 200).sum() for f in gm]
check(min(bm) < 0.01 * gm[0].size, f"Vergleich ohne Auto-Hochkant sollte den Block verlieren: {bm}")
print(f"OK  Echtes Video: Block bleibt im Ausschnitt (kleinster Anteil {min(bright) / g[0].size:.2f}, ohne Auto-Hochkant {min(bm) / gm[0].size:.3f})")

# Entfernen
check(reframe.clear(p) == 1 and not p.clips[0].reframe and reframe.clear(p) == 0, "clear")

# Fehlerfälle
try:
    reframe.analyze_clip(Clip("a.png", 5.0, is_image=True, width=1920, height=1080), 9 / 16)
    check(False, "Standbild")
except reframe.ReframeError:
    pass
bad = Clip(str(tmp / "gibt_es_nicht.mp4"), 5.0, width=1920, height=1080)
r2, n2 = reframe.analyze_project(Project(format_id="shorts", export_id="fast_draft"), [0])
check(r2 == {} and n2 == [], "leeres Projekt")
pb = Project(format_id="shorts", export_id="fast_draft")
pb.clips = [bad]
r3, n3 = reframe.analyze_project(pb, [0])
check(r3 == {} and len(n3) == 1, (r3, n3))
print("ALLES OK")
