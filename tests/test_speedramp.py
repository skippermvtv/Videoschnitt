"""Geschwindigkeitskurve: Abschnitte, Anwenden aufs Projekt und Export (Helligkeit = Quellzeit, Länge, Ton)."""
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
from app.core import exporter, speedramp as sr, window as projwin  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except sr.SpeedRampError as e:
        return str(e)
    return None


# ---------------------------------------------------------------- Eingabe
check(sr.parse_points("0:1, 50:0,25, 100:1") == [[0, 1], [50, 0.25], [100, 1]], sr.parse_points("0:1, 50:0,25, 100:1"))
check(sr.parse_points("0:1; 50:0.25; 100:1") == [[0, 1], [50, 0.25], [100, 1]], "Semikolon")
check(sr.parse_points("0 % : ×2\n100% : 0.5") == [[0, 2], [100, 0.5]], "Zeilenumbruch, %, ×")
check(sr.parse_points("40:2, 60:0.5") == [[0, 2], [40, 2], [60, 0.5], [100, 0.5]], "Anfang und Ende werden ergänzt")
check(sr.parse_points("100:3, 0:1") == [[0, 1], [100, 3]], "Sortieren")
for bad in ("", "abc", "50:1", "0:1, 200:1", "0:0.01, 100:1", "0:1, 100:99", "0:1, 0:2, 100:1", "0:1, 50:x"):
    check(raises(sr.parse_points, bad), f"{bad!r} muss abgelehnt werden")
check(raises(sr.normalize, [[0, float("nan")], [100, 1]]) and raises(sr.normalize, [["a", 1], [100, 1]]), "NaN/Text")
print("OK  Eingabe")

# ---------------------------------------------------------------- Kurve und Abschnitte
pts = sr.normalize([[0, 1], [50, 0.25], [100, 1]])
check(abs(sr.speed_at(pts, 0.0) - 1) < 1e-9 and abs(sr.speed_at(pts, 0.5) - 0.25) < 1e-9 and abs(sr.speed_at(pts, 1.0) - 1) < 1e-9, "Stützpunkte")
check(sr.speed_at(pts, 0.25) < 1.0 and sr.speed_at(pts, 0.25) > 0.25, "weicher Verlauf dazwischen")
for pid, name, pp in sr.PRESETS:
    for seg in (0.5, 3.0, 12.0, 120.0):
        parts = sr.pieces(pp, seg)
        check(1 <= len(parts) <= sr.MAX_PIECES, (pid, seg, len(parts)))
        check(abs(parts[0][0]) < 1e-9 and abs(parts[-1][1] - 1) < 1e-9, f"{pid}: Anfang/Ende")
        check(all(abs(a[1] - b[0]) < 1e-9 for a, b in zip(parts, parts[1:])), f"{pid}: Lücke oder Überlappung")
        check(all(sr.CLIP_MIN <= sp <= sr.CLIP_MAX for _, _, sp in parts), f"{pid}: Tempo außerhalb")
    # Länge entspricht dem Integral der Kurve (fein gerechnet) – Fehler klein
    seg = 10.0
    fine = sum(seg / 4000 / sr.speed_at(sr.normalize(pp), (i + 0.5) / 4000) for i in range(4000))
    got = sr.new_length(pp, seg)
    check(abs(got - fine) / fine < 0.01, f"{pid}: Länge {got:.3f} statt {fine:.3f}")
# Kurvenpunkte sind Schnittstellen; konstantes Tempo → ein einheitlicher Wert
flat = sr.pieces([[0, 2], [100, 2]], 6.0)
check(all(abs(sp - 2.0) < 1e-6 for _, _, sp in flat), flat)
base = sr.pieces([[0, 2], [100, 2]], 6.0, base_speed=1.5)
check(all(abs(sp - 3.0) < 1e-6 for _, _, sp in base), "Grundtempo wird multipliziert")
check(len(sr.pieces(pts, 0.4)) >= 2 and len(sr.pieces(pts, 0.4)) <= 3, "sehr kurzer Clip: wenige Abschnitte")
print("OK  Kurve und Abschnitte")

# ---------------------------------------------------------------- Projekt
p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
c = Clip("x.mp4", 20.0, in_pt=2.0, out_pt=10.0, has_audio=True)
c.grade = {"brightness": 10}
c.transition, c.transition_dur = "fade", 0.7
c.keyframes = [{"t": 0.0, "zoom": 100, "x": 0, "y": 0, "rot": 0}, {"t": 1.0, "zoom": 200, "x": 0, "y": 0, "rot": 0}]
c.motion_ease = False
p.clips = [Clip("a.mp4", 5.0), c, Clip("b.mp4", 5.0)]
before_len = p.duration
used = sr.apply(p, 1, pts)
n = len(used)
check(n >= 5 and len(p.clips) == n + 2 and p.clips[0].path == "a.mp4" and p.clips[-1].path == "b.mp4", (n, len(p.clips)))
pc = p.clips[1:1 + n]
check(abs(pc[0].in_pt - 2.0) < 1e-9 and abs(pc[-1].out_pt - 10.0) < 1e-9, "Quellbereich bleibt vollständig")
check(all(abs(a.out_pt - b.in_pt) < 1e-9 for a, b in zip(pc, pc[1:])), "Abschnitte schließen lückenlos an")
check(len({x.uid for x in pc}) == n, "jeder Abschnitt hat eine eigene Kennung")
check(all(x.transition == "" for x in pc[:-1]) and pc[-1].transition == "fade" and pc[-1].transition_dur == 0.7, "Übergang nur am letzten Abschnitt")
check(all(x.grade == {"brightness": 10} for x in pc) and pc[0].grade is not pc[1].grade, "Bildkorrektur kopiert")
check(abs(sum(x.length for x in pc) - sr.new_length(pts, 8.0)) < 1e-3, "Länge entspricht der Vorhersage")
check(-1e-6 <= sum(x.length for x in p.clips) - p.duration <= 0.7 + 1e-3, "Projektlänge (nur der Übergang darf sie verkürzen)")
# Bewegung (Zoom 100 → 200 über den ganzen Clip): am Anfang jedes Abschnitts der richtige Zoom
for x, (a, b, _sp) in zip(pc, sr.pieces(pts, 8.0)):
    z0 = x.keyframes[0]["zoom"]
    check(abs(z0 - (100 + 100 * a)) < 1.0, f"Bewegung am Abschnittsanfang {a:.2f}: {z0}")
    z1 = x.keyframes[-1]["zoom"]
    check(abs(z1 - (100 + 100 * b)) < 1.0, f"Bewegung am Abschnittsende {b:.2f}: {z1}")
# Fehler
p2 = Project()
p2.clips = [Clip("v.mp4", 10.0), Clip("i.png", 5.0, is_image=True), Clip("r.mp4", 10.0, reverse=True), Clip("k.mp4", 0.3)]
check(raises(sr.apply, p2, 5, pts) and raises(sr.apply, p2, -1, pts), "ungültiger Clip")
check(raises(sr.apply, p2, 1, pts) and raises(sr.apply, p2, 2, pts) and raises(sr.apply, p2, 3, pts), "Bild/Rückwärts/zu kurz")
check(raises(sr.apply, p2, 0, [[0, 1]]), "zu wenige Punkte")
check(len(p2.clips) == 4, "Fehler dürfen das Projekt nicht verändern")
# getrennter Ton wird wieder verbunden
p3 = Project()
p3.clips = [Clip("v.mp4", 10.0, has_audio=True)]
p3.detach_audio(0)
check(p3.clips[0].audio_detached and len(p3.audio_clips) == 1, "Vorbereitung")
sr.apply(p3, 0, pts)
check(not any(x.audio_detached for x in p3.clips) and not p3.audio_clips, "getrennter Ton wieder verbunden")
# Speichern und Laden
q = Project.from_json(p.to_json())
check(len(q.clips) == len(p.clips) and abs(q.duration - p.duration) < 1e-6, "Speichern/Laden")
# Live-Vorschau-Fenster: Länge des Ausschnitts bleibt stimmig
p4 = Project(format_id="youtube_16_9", export_id="youtube_1080p")
p4.clips = [Clip("v.mp4", 12.0, in_pt=0.0, out_pt=12.0, has_audio=False)]
sr.apply(p4, 0, [[0, 1], [50, 0.3], [100, 1]])
wp, off, ln = projwin.project_window(p4, 2.0, 4.0)
check(ln > 3.0 and wp.clips, (off, ln, len(wp.clips)))
print("OK  Projekt")

# ---------------------------------------------------------------- Export: Helligkeit = Quellzeit
DUR = 6.0
src = tmp / "ramp.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=160x90:r=25:d={DUR},geq=lum='16+219*T/{DUR}':cb=128:cr=128",
                "-f", "lavfi", "-i", f"sine=f=440:d={DUR}", "-shortest", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(src)], check=True)
info = probe(str(src))
pr = Project(format_id="youtube_16_9", export_id="youtube_1080p")
pr.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height)]
curve = [[0, 1], [40, 1], [55, 0.3], [70, 1], [100, 2]]
parts = sr.pieces(sr.normalize(curve), DUR)
sr.apply(pr, 0, curve)
check(len(pr.clips) >= 6, len(pr.clips))
out = tmp / "ramp_out.mp4"
cmd, total, _ = exporter.build_command(pr, str(out), draft=True, preview_height=180)
exporter.run(cmd, total)
oi = probe(str(out))
check(abs(oi.duration - pr.duration) < 0.25, f"Exportlänge {oi.duration:.2f} s statt {pr.duration:.2f} s")


def lum_at(t):
    png = tmp / "f.png"
    subprocess.run([ff, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(out), "-frames:v", "1", str(png)], check=True)
    return float(np.array(Image.open(png).convert("L")).astype(float)[20:70, 40:120].mean())


def src_time(t_line):
    """Quellzeit, die laut Kurve zur Zeitlinienzeit t gehört."""
    acc = 0.0
    for a, b, sp in parts:
        d = (b - a) * DUR / sp
        if t_line <= acc + d + 1e-9:
            return (a + (t_line - acc) / d * (b - a)) * DUR
        acc += d
    return DUR


worst = 0.0
prev = -1.0
for i in range(1, 30):
    t = pr.duration * i / 30.0
    got = lum_at(t) / 255.0 * DUR                               # gemessene Quellzeit
    want = src_time(t)
    worst = max(worst, abs(got - want))
    check(got >= prev - 0.15, f"Quellzeit springt rückwärts bei {t:.2f} s ({prev:.2f} → {got:.2f})")
    prev = got
check(worst < 0.3, f"Bild folgt der Kurve nicht: größte Abweichung {worst:.2f} s Quellzeit")
a = subprocess.run([ff, "-v", "error", "-i", str(out), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
x = np.frombuffer(a, dtype=np.float32)
check(abs(len(x) / 48000 - oi.duration) < 0.3 and float(np.sqrt(np.mean(x.astype(float) ** 2))) > 0.05, f"Ton: {len(x) / 48000:.2f} s, Pegel {np.sqrt(np.mean(x.astype(float) ** 2)):.3f}")
print(f"OK  Export: Länge {oi.duration:.2f} s, größte Abweichung {worst:.2f} s Quellzeit")

# mit Übergang zum nächsten Clip und Bewegung: Export läuft durch
pr2 = Project(format_id="youtube_16_9", export_id="youtube_1080p")
pr2.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height),
             Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height)]
pr2.clips[0].transition, pr2.clips[0].transition_dur = "fade", 0.6
pr2.clips[0].keyframes = [{"t": 0.0, "zoom": 100, "x": 0, "y": 0, "rot": 0}, {"t": 1.0, "zoom": 150, "x": 0, "y": 0, "rot": 0}]
pr2.clips[0].stabilize = 0
sr.apply(pr2, 0, [[0, 2], [100, 0.5]])
out2 = tmp / "ramp2.mp4"
cmd, total, _ = exporter.build_command(pr2, str(out2), draft=True, preview_height=180)
exporter.run(cmd, total)
check(out2.exists() and abs(probe(str(out2)).duration - pr2.duration) < 0.35, f"Länge mit Übergang: {probe(str(out2)).duration:.2f} / {pr2.duration:.2f}")
print("OK  Export mit Übergang und Bewegung")
print("ALLES OK")
