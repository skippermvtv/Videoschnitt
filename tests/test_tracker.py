"""Tracking: Korrelation, Pfad aufbereiten und ein ganzer Durchlauf mit echtem FFmpeg (bewegtes Objekt auf Rauschen)."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import effects as fx, tracker  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
rng = np.random.default_rng(7)


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# ---------------------------------------------------------------- Korrelation
bg = rng.integers(0, 255, (80, 120)).astype(np.uint8)
patch = bg[30:46, 50:66].copy()
m = tracker.ncc_map(bg, patch)
iy, ix = divmod(int(np.argmax(m)), m.shape[1])
check((ix, iy) == (50, 30) and m[iy, ix] > 0.99, (ix, iy, m[iy, ix]))
check(tracker.ncc_map(bg, np.full((8, 8), 7, np.uint8)).max() == 0.0, "einfarbige Vorlage")
print("OK  Korrelation")

# ---------------------------------------------------------------- Pfad
pts = [[i * 0.1, 10 + i * 1.0, 50.0] for i in range(40)]                 # gerade Linie → nur 2 Punkte
check(len(tracker.simplify(pts, 0.2)) == 2, len(tracker.simplify(pts, 0.2)))
zig = [[i * 0.1, 50 + (5 if i % 2 else -5), 50.0] for i in range(100)]
red = tracker.reduce_points(zig, limit=40)
check(len(red) <= 40 and red[0][0] == 0.0 and abs(red[-1][0] - 9.9) < 1e-6, (len(red), red[0], red[-1]))
sm = tracker.smooth(zig, 5)
check(max(abs(p[1] - 50) for p in sm[5:-5]) < 3.0, "Glättung")
print("OK  Pfad")

# ---------------------------------------------------------------- Ganzer Ablauf
W, H, FPS, SEC = 320, 180, 25, 4
n = FPS * SEC
bgimg = rng.integers(40, 215, (H, W)).astype(np.uint8)
sprite = (rng.integers(0, 255, (28, 28))).astype(np.uint8)
sprite[::7, :] = 255
truth = []
raw = bytearray()
for i in range(n):
    u = i / (n - 1)
    cx = 25 + 50 * u                       # % → 25 … 75
    cy = 50 + 20 * np.sin(u * 2 * np.pi)   # % → 30 … 70
    truth.append((cx, cy))
    fr = bgimg.copy()
    x0, y0 = int(round(cx / 100 * W - 14)), int(round(cy / 100 * H - 14))
    fr[y0:y0 + 28, x0:x0 + 28] = sprite
    raw += fr.tobytes()
src = tmp / "moving.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(src)], input=bytes(raw), check=True)
info = probe(str(src))
p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
p.clips = [Clip(str(src), info.duration, has_audio=False, width=info.width, height=info.height)]
p.effects = [{"id": "mask_mosaic", "intensity": 60, "start": 0.0, "end": None,
              "mask": {"shape": "rect", "x": 25.0, "y": 50.0, "w": 14.0, "h": 24.0, "feather": 10}}]
prog = []
res = tracker.track_block(p, 0, height=180, fps=12.0, on_progress=prog.append)
check(res.frames >= 40 and res.lost <= 2, (res.frames, res.lost))
check(2 <= len(res.points) <= tracker.MAX_POINTS, len(res.points))
check(prog and prog[-1] > 0.9, "Fortschritt")
# Pfad gegen die Wahrheit (Zeit t → Prozentwerte)


def path_at(t):
    xs = [q[0] for q in res.points]
    return float(np.interp(t, xs, [q[1] for q in res.points])), float(np.interp(t, xs, [q[2] for q in res.points]))


worst = 0.0
for k in range(0, n, 5):
    t = k / FPS
    px, py = path_at(t)
    worst = max(worst, abs(px - truth[k][0]), abs(py - truth[k][1]))
check(worst < 3.0, f"Pfad weicht um {worst:.2f} % ab")
print(f"OK  Durchlauf: {len(res.points)} Punkte, größte Abweichung {worst:.2f} %")

# Pfad im Block → Export-Befehl enthält die Bewegung, Projekt wird nicht verändert
check("track" not in p.effects[0]["mask"] or not p.effects[0]["mask"]["track"], "track_block darf das Projekt nicht ändern")
p.effects[0]["mask"]["track"] = res.points
mp = fx.mask_params(p.effects[0]["mask"])
check(len(mp["track"]) == len(res.points), "Pfad wird von mask_params übernommen")
expr = fx.mask_expression(p.effects[0]["mask"], 0.0)
check("lt((T-0)" in expr, expr[:120])
print("OK  Pfad im Maskenausdruck")

# Fehlerfälle
try:
    tracker.track_block(p, 5)
    check(False, "falscher Index")
except tracker.TrackError:
    pass
p.effects.append({"id": "vhs", "intensity": 50, "start": 0.0, "end": 2.0})
try:
    tracker.track_block(p, 1)
    check(False, "Effekt ohne Bereich")
except tracker.TrackError:
    pass
p.effects[0]["start"], p.effects[0]["end"] = 1.0, 1.1
try:
    tracker.track_block(p, 0)
    check(False, "zu kurzer Block")
except tracker.TrackError:
    pass
try:
    tracker.follow(np.zeros((3, 40, 40), np.uint8), (20, 20, 10, 10), should_cancel=lambda: True)
    check(False, "Abbruch")
except tracker.TrackError as exc:
    check("Abgebrochen" in str(exc), exc)
print("OK  Fehlerfälle")
print("ALLES OK")
