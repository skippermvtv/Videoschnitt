"""YouTube-Kapitel aus Markern (Projektdaten)."""
import os
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import chapters  # noqa: E402
from app.core.project import Clip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def proj(markers, total=300.0):
    p = Project()
    p.clips = [Clip("a.mp4", total, 0.0, total)]
    p.markers = markers
    return p


check(chapters.fmt(0) == "0:00" and chapters.fmt(59.9) == "0:59" and chapters.fmt(61) == "1:01" and chapters.fmt(600) == "10:00", "m:ss")
check(chapters.fmt(3600) == "1:00:00" and chapters.fmt(3725.4) == "1:02:05" and chapters.fmt(-5) == "0:00", "h:mm:ss")

# gültige Liste
r = chapters.build(proj([{"t": 0, "name": "Intro"}, {"t": 45.7, "name": "Aufbau"}, {"t": 130, "name": "Test"}, {"t": 250, "name": "Fazit"}]))
check(r["ok"] and r["text"] == "0:00 Intro\n0:45 Aufbau\n2:10 Test\n4:10 Fazit" and not r["notes"], r)
print("OK  gültige Liste")

# fehlendes 0:00 wird ergänzt, unbenannte ignoriert
r = chapters.build(proj([{"t": 20, "name": "Teil 1"}, {"t": 60, "name": ""}, {"t": 100, "name": "Teil 2"}]), intro="Begrüßung")
check(r["items"][0] == (0, "Begrüßung") and len(r["items"]) == 3 and r["ok"], r)
check(any("0:00" in n for n in r["notes"]) and any("ohne Namen" in n for n in r["notes"]), r["notes"])
print("OK  0:00 ergänzt, unbenannte ignoriert")

# zu wenige
r = chapters.build(proj([{"t": 0, "name": "A"}, {"t": 50, "name": "B"}]))
check(not r["ok"] and any("mindestens 3" in x for x in r["problems"]), r["problems"])
r = chapters.build(proj([]))
check(not r["ok"] and r["text"] == "0:00 Anfang", r)
print("OK  zu wenige Kapitel")

# zu kurz (inkl. letztes Kapitel bis Videoende)
r = chapters.build(proj([{"t": 0, "name": "A"}, {"t": 5, "name": "B"}, {"t": 100, "name": "C"}, {"t": 295, "name": "D"}]))
check(not r["ok"] and any("kürzer" in x and "0:00 A" in x and "4:55 D" in x for x in r["problems"]), r["problems"])
print("OK  zu kurze Kapitel")

# gleiche Sekunde, hinter dem Ende, Leerzeichen
r = chapters.build(proj([{"t": 0, "name": " A  b "}, {"t": 30.2, "name": "X"}, {"t": 30.8, "name": "Y"}, {"t": 400, "name": "Z"}, {"t": 120, "name": "W"}]))
check(any("derselben Sekunde" in x for x in r["problems"]) and any("hinter dem Ende" in n for n in r["notes"]), r)
check(r["items"][0] == (0, "A b"), r["items"])
print("OK  Sonderfälle")
print("ALLES OK")
