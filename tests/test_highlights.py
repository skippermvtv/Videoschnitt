"""Highlights finden: Bewertung (reine Rechnung), echtes Video mit lauter Stelle, Marker, Randfälle."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
tmp.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import highlights as hl  # noqa: E402
from app.core.project import Clip, Project, SubtitleCue, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# --- reine Rechnung
loud = np.full(120, -50.0)
loud[60:80] = -20.0
loud[70] = -8.0
s, r = hl.score_windows(loud, np.zeros(120), np.zeros(120), 20.0)
check(len(s) == 101 and int(np.argmax(s)) == 60, (len(s), int(np.argmax(s))))
top = hl.pick(s, r, 20.0, 3, 120.0)
check(len(top) == 3 and all(a.end <= b.start + 1e-9 for a, b in zip(top, top[1:])), top)
check(max(top, key=lambda h: h.score).start == 60.0 and "laut" in max(top, key=lambda h: h.score).reasons, top)
check(hl.pick(s, r, 20.0, 1, 120.0)[0].start == 60.0, "bestes Fenster zuerst")
# Gleichstand (alles gleich laut) darf nicht scheitern
flat, rf = hl.score_windows(np.full(60, -30.0), np.zeros(60), np.zeros(60), 10.0)
check(np.allclose(flat, flat[0]), "Gleichstand")
# Sprechdichte zieht an, wenn die Lautstärke gleich ist
sp = np.zeros(120)
sp[20:40] = 3.0
s2, r2 = hl.score_windows(np.full(120, -30.0), sp, np.zeros(120), 20.0)
check(int(np.argmax(s2)) == 20 and "viel gesprochen" in r2[20], int(np.argmax(s2)))
try:
    hl.score_windows(np.full(5, -30.0), np.zeros(5), np.zeros(5), 20.0)
    check(False, "zu kurz hätte scheitern müssen")
except hl.HighlightError:
    pass
print("OK  Bewertung")

# --- echtes Video: 70 s leises Rauschen, laute Stelle 30–50 s
ff = find_binary("ffmpeg")
vid = tmp / "hl_burst.mp4"
expr = "0.01*sin(2*PI*220*t)+0.6*sin(2*PI*440*t)*between(t,30,50)"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x305090:s=160x90:r=10:d=70", "-f", "lavfi",
                "-i", f"aevalsrc='{expr}':s=22050:d=70", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(vid)], check=True)
info = probe(str(vid))
p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
p.clips = [Clip(str(vid), info.duration, has_audio=True, width=160, height=90)]
bins = hl.loudness_bins(p)
check(len(bins) >= 69 and bins[40] > bins[10] + 15, (len(bins), bins[10], bins[40]))
found = hl.find(p, window=20.0, count=2)
check(found and found[0].length == 20.0, found)
best = max(found, key=lambda h: h.score)
check(30.0 <= best.start + 0.5 and best.end <= 50.5, f"bester Abschnitt {best.start}–{best.end} liegt nicht in der lauten Stelle")
n = hl.apply_markers(p, found)
distinct = len({round(t, 2) for h in found for t in (h.start, h.end)})      # Ende des einen = Anfang des nächsten → ein gemeinsamer Marker
check(n == distinct and n >= len(found) + 1 and p.markers[0]["name"].startswith("★"), (n, distinct, p.markers))
check("Highlight" in hl.describe(found[0], 1), hl.describe(found[0], 1))
print(f"OK  echtes Video: bester Abschnitt {best.start:.0f}–{best.end:.0f} s ({', '.join(best.reasons)})")

# Tempo ×2 + zweiter Clip: Zeiten liegen auf der Timeline
p2 = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
p2.clips = [Clip(str(vid), info.duration, has_audio=True, width=160, height=90, in_pt=0.0, out_pt=30.0),
            Clip(str(vid), info.duration, has_audio=True, width=160, height=90, in_pt=30.0, out_pt=50.0, speed=2.0)]
b2 = hl.loudness_bins(p2)
check(len(b2) >= 39 and b2[35] > b2[10] + 15 and b2[28] < b2[35], (len(b2), b2[10], b2[28], b2[35]))   # laut ab Timeline-Sekunde 30
print("OK  Tempo und mehrere Clips")

# Randfälle
try:
    hl.find(Project(), 30.0, 3)
    check(False, "leeres Projekt")
except hl.HighlightError:
    pass
short = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
short.clips = [Clip(str(vid), info.duration, has_audio=True, width=160, height=90, in_pt=0.0, out_pt=10.0)]
try:
    hl.find(short, 30.0, 3)
    check(False, "zu kurz")
except hl.HighlightError as exc:
    check("zu kurz" in str(exc), exc)
q = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
q.clips = [Clip(str(vid), info.duration, has_audio=False, width=160, height=90, in_pt=0.0, out_pt=40.0)]
try:
    hl.find(q, 10.0, 3)
    check(False, "ohne Ton")
except hl.HighlightError as exc:
    check("keinen Ton" in str(exc), exc)
q.subtitles = [SubtitleCue(5.0, 8.0, "ein paar Wörter hier", [])]
check(hl.find(q, 10.0, 2), "mit Untertiteln auch ohne Ton")
print("OK  Randfälle")
print("ALLES OK")
