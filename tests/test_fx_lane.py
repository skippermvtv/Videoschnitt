"""Effekt-Spur (FX): Blöcke mit Zeitfenster, mehrere Blöcke desselben Effekts, Rückwärtskompatibilität (echtes FFmpeg)."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("FEHLER", msg)


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


red = tmp / "red10.mp4"
sh("-f", "lavfi", "-i", "color=c=0xe01010:s=320x180:r=25:d=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(red))
info = probe(str(red))


def project():
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(red), info.duration, has_audio=False, width=info.width, height=info.height)]
    return p


def px(p, t, name):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    png = tmp / f"{name}.png"
    sh("-ss", f"{t}", "-i", str(out), "-frames:v", "1", str(png))
    im = np.array(Image.open(png).convert("RGB")).astype(int)
    h, w, _ = im.shape
    return tuple(im[h // 2, w // 2])


def is_red(c):
    return c[0] > 150 and c[1] < 90 and c[2] < 90


def is_gray(c):
    return max(c) - min(c) < 30


# --- Modell: Blöcke anlegen, Zeiten, Zeilen
p = project()
a = p.fx_add("bw", 100, 2.0, 2.0)                    # 2 … 4 s
b = p.fx_add("bw", 100, 6.0, 2.0)                    # 6 … 8 s, derselbe Effekt noch einmal
check(p.fx_span(a) == (2.0, 4.0) and p.fx_span(b) == (6.0, 8.0), f"Zeiten falsch: {p.fx_span(a)} {p.fx_span(b)}")
check(p.fx_rows() == [0, 0], "nicht überlappende Blöcke gehören in eine Zeile")
c = p.fx_add("blur", 50, 3.0, 4.0)                   # überlappt beide
check(p.fx_rows()[c] == 1, f"überlappender Block braucht Zeile 2: {p.fx_rows()}")
p.effects.pop()
w = p.fx_add("vignette", 60, 0.0, 999.0)             # ganze Länge -> keine Zeiten gespeichert
check("start" not in p.effects[w] and "end" not in p.effects[w], f"Ganzer Block sollte keine Zeiten haben: {p.effects[w]}")
p.effects.pop()
p.fx_set_span(a, 8.0, 7.0)                           # Ende vor Anfang -> mindestens FX_MIN
check(p.fx_span(a)[1] - p.fx_span(a)[0] >= p.FX_MIN - 1e-9, "Mindestlänge")
p.fx_set_span(a, 2.0, 4.0)
print("OK  Modell: Blöcke, Zeilen, Mindestlänge")

# --- Export: Effekt wirkt nur im Block, beide Blöcke desselben Effekts wirken
check(is_red(px(p, 1.0, "fx_a")) and is_gray(px(p, 3.0, "fx_b")) and is_red(px(p, 5.0, "fx_c")) and is_gray(px(p, 7.0, "fx_d"))
      and is_red(px(p, 9.0, "fx_e")), "S/W-Blöcke wirken nicht zur richtigen Zeit")
print("OK  Export: zwei Blöcke desselben Effekts, rot – grau – rot – grau – rot")

# Block verschieben -> Wirkung wandert mit
p.fx_set_span(a, 4.5, 6.0)
check(is_red(px(p, 3.0, "fx_f")) and is_gray(px(p, 5.0, "fx_g")), "verschobener Block wirkt nicht an der neuen Stelle")
print("OK  Export: verschobener Block")

# --- Rückwärtskompatibilität: altes Projekt (Effekte ohne Zeiten, mit start/end None) lädt und exportiert
old = project()
old.effects = [{"id": "bw", "intensity": 100}]
f = tmp / "alt.cforge"
old.save(str(f))
d = json.loads(f.read_text(encoding="utf-8"))
check(d["effects"] == [{"id": "bw", "intensity": 100}], "Speicherformat unverändert")
q = Project.load(str(f))
check(q.fx_span(0) == (0.0, 10.0), f"Ganzer Effekt: {q.fx_span(0)}")
check(is_gray(px(q, 1.0, "fx_h")) and is_gray(px(q, 9.0, "fx_i")), "alter Effekt wirkt nicht über die ganze Länge")
old.effects = [{"id": "bw", "intensity": 100, "start": 3.0, "end": None}]
check(old.fx_span(0) == (3.0, 10.0) and is_red(px(old, 1.0, "fx_j")) and is_gray(px(old, 8.0, "fx_k")), "alter Effekt ab Zeitpunkt")
print("OK  Rückwärtskompatibel (altes Projektformat)")

print("ALLES OK ->" if not fails else f"{len(fails)} FEHLER ->", tmp)
sys.exit(1 if fails else 0)
