"""Tempokurve nachträglich ändern: Abschnitte merken ihre Kurve, „neu anwenden“ ersetzt sie, Zusammenführen stellt den Clip her."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import speedramp as sr  # noqa: E402
from app.core.project import Clip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def make(n=3):
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip("a.mp4", 10.0, in_pt=1.0, out_pt=9.0, speed=1.5), Clip("b.mp4", 6.0), Clip("c.mp4", 4.0)][:n]
    p.clips[0].keyframes = [{"t": 0.0, "zoom": 100, "x": 0, "y": 0, "rot": 0}, {"t": 1.0, "zoom": 200, "x": 0, "y": 0, "rot": 0}]
    p.clips[0].motion_ease = False
    p.clips[0].transition, p.clips[0].transition_dur = "fade", 0.5
    return p


def key(c):
    return (c.path, round(c.in_pt, 4), round(c.out_pt, 4), c.speed, c.transition, json.dumps(c.keyframes), c.motion_ease)


p = make()
orig = key(p.clips[0])
check(sr.group_of(p, 0) is None and sr.curve_of(p, 0) is None, "ohne Kurve keine Gruppe")
curve = [[0, 1], [50, 0.25], [100, 1]]
used = sr.apply(p, 0, curve)
n1 = len(used)
check(n1 >= 5 and len(p.clips) == n1 + 2, (n1, len(p.clips)))
gid = p.clips[0].ramp_id
check(gid and all(p.clips[k].ramp_id == gid for k in used) and p.clips[n1].ramp_id == "", "alle Abschnitte tragen dieselbe Kennung, andere Clips nicht")
check(sr.group_of(p, n1 // 2) == (0, n1 - 1), sr.group_of(p, n1 // 2))
check(sr.curve_of(p, 2) == [[0.0, 1.0], [50.0, 0.25], [100.0, 1.0]], sr.curve_of(p, 2))
check(all(c.ramp_speed == 1.5 for c in p.clips[:n1]), "Grundtempo wird gemerkt (nicht das Tempo eines Abschnitts)")
check(p.clips[n1 - 1].transition == "fade" and all(c.transition == "" for c in p.clips[:n1 - 1]), "Übergang nur am letzten Abschnitt")
print("OK  Kurve merken")

# Zusammenführen stellt den Clip wie vorher her
idx = sr.merge_group(p, n1 - 2)
check(idx == 0 and len(p.clips) == 3 and key(p.clips[0]) == orig, (key(p.clips[0]), orig))
check(p.clips[0].ramp_id == "" and p.clips[0].ramp_pts == [], "Kurven-Merkmal ist weg")
check(p.clips[1].path == "b.mp4" and p.clips[2].path == "c.mp4", "andere Clips bleiben")
print("OK  Zusammenführen")

# Neu anwenden ersetzt die Kurve (auch wenn man einen mittleren Abschnitt gewählt hat)
p = make()
sr.apply(p, 0, curve)
n_a = len([c for c in p.clips if c.path == "a.mp4"])
used2 = sr.apply(p, 2, [[0, 2], [100, 0.5]])
check(len(p.clips) == len(used2) + 2, f"alte Abschnitte sind ersetzt: {len(p.clips)} Clips, {len(used2)} neue")
check(sr.curve_of(p, 0) == [[0.0, 2.0], [100.0, 0.5]] and p.clips[0].ramp_id != gid, "neue Kurve und neue Kennung")
check(abs(p.clips[0].in_pt - 1.0) < 1e-9 and abs(p.clips[used2[-1]].out_pt - 9.0) < 1e-9, "Quellbereich unverändert")
check(p.clips[used2[-1]].transition == "fade" and p.clips[0].ramp_speed == 1.5, "Übergang und Grundtempo bleiben")
check(abs(sum((c.out_pt - c.in_pt) for c in p.clips[:len(used2)]) - 8.0) < 1e-6, "Abschnitte decken genau die 8 s ab")
total = sum(c.length for c in p.clips[:len(used2)])
check(abs(total - sr.new_length([[0, 2], [100, 0.5]], 8.0, 1.5)) < 0.01, f"Länge {total:.3f}")
check(n_a == n1, "erste Kurve hatte gleich viele Abschnitte wie zuvor")
print("OK  Neu anwenden")

# Ungültige neue Kurve ändert nichts
p = make()
sr.apply(p, 0, curve)
before = [key(c) for c in p.clips]
try:
    sr.apply(p, 1, [[0, 99], [100, 1]])
    check(False, "ungültige Kurve muss abgelehnt werden")
except sr.SpeedRampError:
    pass
check([key(c) for c in p.clips] == before and sr.group_of(p, 0) is not None, "nach Fehler unverändert")
print("OK  Fehler ändert nichts")

# Veränderte Abschnitte: Lücke / Verschieben / Kürzen → keine Gruppe, apply teilt nur den gewählten Abschnitt
p = make()
sr.apply(p, 0, curve)
big = 3
check(big > 0 and p.clips[big].out_pt - p.clips[big].in_pt > 0.45, "Testaufbau: langer Abschnitt")
p.clips[big].in_pt += 0.05                                          # einen Abschnitt vorn gekürzt
check(sr.group_of(p, 0) is None and sr.curve_of(p, 0) is None, "Lücke → keine Gruppe")
try:
    sr.merge_group(p, 0)
    check(False, "Zusammenführen bei Lücke muss abgelehnt werden")
except sr.SpeedRampError:
    pass
n_before = len(p.clips)
used3 = sr.apply(p, big, [[0, 1], [100, 2]])
check(len(p.clips) == n_before - 1 + len(used3) and p.clips[used3[0]].ramp_id != gid, "alter Rest wird nicht angerührt, neuer Abschnitt bekommt eigene Kurve")
p = make()
sr.apply(p, 0, curve)
p.clips[1], p.clips[3] = p.clips[3], p.clips[1]                     # Abschnitte vertauscht
check(sr.group_of(p, 0) is None, "vertauscht → keine Gruppe")
p = make()
sr.apply(p, 0, curve)
moved = p.clips.pop(2)
p.clips.append(moved)                                               # ein Abschnitt ans Ende verschoben
check(sr.group_of(p, 0) is None, "verstreut → keine Gruppe")
print("OK  Veränderte Abschnitte")

# Speichern/Laden, altes Projekt
p = make()
sr.apply(p, 0, curve)
q = Project.from_json(p.to_json())
check(sr.group_of(q, 3) == sr.group_of(p, 3) and sr.curve_of(q, 3) == sr.curve_of(p, 3), "Speichern/Laden")
d = json.loads(p.to_json())
for c in d["clips"]:
    for k in ("ramp_id", "ramp_pts", "ramp_speed", "ramp_keys", "ramp_ease"):
        c.pop(k, None)
old = Project.from_json(json.dumps(d))
check(all(c.ramp_id == "" and sr.group_of(old, i) is None for i, c in enumerate(old.clips)), "altes Projekt ohne Kurvenmerkmale")
print("OK  Speichern/Laden, altes Projekt")
print("ALLES OK")
