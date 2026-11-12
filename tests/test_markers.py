"""Marker: setzen, bereinigen, springen, Speichern/Laden, Einrasten in der Timeline-Logik."""
import json
import os
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import markers as mk  # noqa: E402
from app.core.project import Clip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


p = Project()
p.clips = [Clip("a.mp4", 10.0, 0.0, 10.0)]
check(p.markers == [], "leer am Anfang")
i = mk.add(p, 4.0, "Drop")
check(i == 0 and p.markers == [{"t": 4.0, "name": "Drop"}], p.markers)
check(mk.add(p, 4.02) == 0 and len(p.markers) == 1, "nah beieinander = derselbe Marker")
mk.add(p, 1.0)
mk.add(p, 7.5, "Ende")
check(mk.times(p) == [1.0, 4.0, 7.5], mk.times(p))
check(p.markers[mk.add(p, 1.0)]["t"] == 1.0, "Index stimmt nach Sortierung")
check(mk.nearest(p, 4.1) == 1 and mk.nearest(p, 5.5) == -1 and mk.nearest(p, 5.5, 2.0) == 1, "nearest")
check(mk.step(p, 0.0, 1) == 1.0 and mk.step(p, 1.0, 1) == 4.0 and mk.step(p, 7.5, 1) is None, "nächster")
check(mk.step(p, 4.0, -1) == 1.0 and mk.step(p, 1.0, -1) is None and mk.step(p, 9.0, -1) == 7.5, "vorheriger")
check(mk.rename(p, 0, "Start") and p.markers[0]["name"] == "Start" and not mk.rename(p, 9, "x"), "umbenennen")
check(mk.remove(p, 0) and mk.times(p) == [4.0, 7.5] and not mk.remove(p, 5), "entfernen")
check(mk.add_many(p, [0.5, 1.5, 4.01, 2.5]) == 3 and mk.times(p) == [0.5, 1.5, 2.5, 4.0, 7.5], f"add_many {mk.times(p)}")
check(mk.step(p, 9.0, 1) is None, "kein nächster am Ende")
print("OK  Grundfunktionen")

# Bereinigen: Müll aus beschädigten Dateien
bad = mk.clean([None, 5, {"t": "abc"}, {"t": -1}, {"t": float("nan")}, {"t": 3, "name": "x" * 200}, {"t": 3.01}, {"t": 2}])
check([m["t"] for m in bad] == [2.0, 3.0] and len(bad[1]["name"]) == 60, bad)
big = mk.clean([{"t": i * 0.1} for i in range(2000)])
check(len(big) == mk.MAX_MARKERS, len(big))
print("OK  Bereinigen")

# Speichern/Laden, altes Projekt
f = tmp / "p.json"
p.save(str(f))
q = Project.load(str(f))
check(q.markers == p.markers, "Laden")
d = json.loads(p.to_json())
d.pop("markers")
check(Project.from_json(json.dumps(d)).markers == [], "altes Projekt")
check(mk.clear(q) == 5 and q.markers == [], "alle entfernen")
broken = json.loads(p.to_json())
broken["markers"] = [None, {"t": "x"}, {"t": 2.0, "name": "ok"}]
check(Project.from_json(json.dumps(broken)).markers == [{"t": 2.0, "name": "ok"}], "beschädigte Marker beim Laden bereinigt")
print("OK  Speichern/Laden")
print("ALLES OK")
