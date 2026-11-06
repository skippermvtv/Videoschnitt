"""Split Screen: Felder, Zuordnung und Export (Pixeltest mit vier Farbvideos)."""
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
from app.core import exporter, split, window as projwin  # noqa: E402
from app.core.project import Clip, OverlayClip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# ---------------------------------------------------------------- Felder
for lid, name, cells in split.LAYOUTS:
    area = sum(c[2] * c[3] for c in cells)
    check(abs(area - 10000.0) < 0.01, f"{lid}: Felder füllen das Bild nicht ganz ({area})")
    for a in range(len(cells)):
        for b in range(a + 1, len(cells)):
            A, B = cells[a], cells[b]
            ox = min(A[0] + A[2], B[0] + B[2]) - max(A[0], B[0])
            oy = min(A[1] + A[3], B[1] + B[3]) - max(A[1], B[1])
            check(not (ox > 1e-6 and oy > 1e-6), f"{lid}: Felder {a}/{b} überlappen")
# Bildpunkte: lückenlos, auch bei krummen Größen
for W, H in ((1920, 1080), (1080, 1920), (1001, 777)):
    for lid, name, cells in split.LAYOUTS:
        cover = np.zeros((H, W), dtype=int)
        for c in cells:
            x0, y0, w, h = split.cell_px(OverlayClip("a.mp4", 1.0, cell=c), W, H)
            cover[y0:y0 + h, x0:x0 + w] += 1
        check(cover.min() == 1 and cover.max() == 1, f"{lid} {W}x{H}: Lücke oder Überlappung ({cover.min()}…{cover.max()})")
check(split.cell_px(OverlayClip("a.mp4", 1.0), 1920, 1080) is None, "ohne Feld kein Split")
for bad in ([1, 2, 3], "abc", [0, 0, 0, 0], [0, 0, float("nan"), 50], [90, 0, 50, 50], [-5, 0, 50, 50], None):
    check(split.valid_cell(bad) is None, f"kaputtes Feld {bad!r} muss verworfen werden")
print("OK  Felder")

# ---------------------------------------------------------------- Zuordnung
p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
p.overlays = [OverlayClip("a.mp4", 10.0, start=0.0), OverlayClip("b.mp4", 10.0, start=2.0), OverlayClip("c.mp4", 10.0, start=5.0),
              OverlayClip("d.mp4", 3.0, start=20.0)]
check(split.candidates(p, 1, 0.0) == [1, 0, 2], split.candidates(p, 1, 0.0))
check(split.candidates(p, -1, 6.0) == [0, 1, 2], split.candidates(p, -1, 6.0))
check(split.candidates(p, -1, 15.0) == [], "um 15 s läuft nichts")
used = split.apply(p, "3l", sel=1)
check(used == [1, 0, 2] and p.overlays[1].cell == [0, 0, 50, 100] and p.overlays[0].cell == [50, 0, 50, 50], (used, [o.cell for o in p.overlays]))
check(p.overlays[3].cell == [], "nicht beteiligter Block bleibt unberührt")
used = split.apply(p, "2h", indices=[2, 0, 1])
check(used == [2, 0] and p.overlays[2].cell == [0, 0, 50, 100] and p.overlays[0].cell == [50, 0, 50, 100], "ausdrückliche Auswahl")
for o in p.overlays:
    o.cell = []
used = split.apply(p, "3l", sel=1)
try:
    split.apply(p, "4", sel=1)
    check(False, "vier Felder mit drei Blöcken muss scheitern")
except split.SplitError as e:
    check("4" in str(e) and "3" in str(e), str(e))
check(split.clear(p, [0]) == 1 and p.overlays[0].cell == [] and p.overlays[1].cell, "einzelnes Feld löschen")
check(split.clear(p) == 2 and not any(o.cell for o in p.overlays), "alles löschen")
try:
    split.layout("gibtsnicht")
    check(False, "unbekanntes Layout")
except split.SplitError:
    pass
q = Project.from_json(Project(overlays=[OverlayClip("a.mp4", 5.0, cell=[0, 0, 50, 50])]).to_json())
check(q.overlays[0].cell == [0, 0, 50, 50], "Speichern/Laden")
check(Project.from_json('{"overlays":[{"path":"a.mp4","duration":3.0}]}').overlays[0].cell == [], "altes Projekt")
print("OK  Zuordnung")

# ---------------------------------------------------------------- Export, Pixeltest
cols = {"red": "0xff0000", "green": "0x00ff00", "blue": "0x0000ff", "yellow": "0xffff00"}
srcs = {}
for name, col in cols.items():
    f = tmp / f"{name}.mp4"
    size = "640x360" if name != "blue" else "360x640"                          # eines im Hochformat: muss trotzdem füllen
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s={size}:r=25:d=4", "-c:v", "libx264", "-pix_fmt", "yuv444p",
                    str(f)], check=True)
    srcs[name] = f
base = tmp / "gray.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=640x360:r=25:d=4", "-f", "lavfi", "-i", "sine=d=4",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(base)], check=True)
binfo = probe(str(base))
order = ["red", "green", "blue", "yellow"]
RGB = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0)}


def make_project():
    pr = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    pr.clips = [Clip(str(base), binfo.duration, has_audio=True, width=binfo.width, height=binfo.height)]
    for nm in order:
        i = probe(str(srcs[nm]))
        pr.overlays.append(OverlayClip(str(srcs[nm]), i.duration, 0.0, i.duration, start=0.0))
    return pr


def frame(pr, name, at=1.5):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(pr, str(out), draft=True, preview_height=360)
    exporter.run(cmd, total)
    png = tmp / f"{name}.png"
    subprocess.run([ff, "-v", "error", "-y", "-ss", str(at), "-i", str(out), "-frames:v", "1", str(png)], check=True)
    return np.array(Image.open(png).convert("RGB")).astype(int)


def near(px, rgb, tol=40):
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(px, rgb))


def at(im, fx, fy):
    h, w = im.shape[:2]
    return im[int(h * fy), int(w * fx)]


def expect(im, layout_id, label):
    name, cells = split.layout(layout_id)
    for nm, c in zip(order, cells):
        for fx, fy in ((0.2, 0.2), (0.5, 0.5), (0.8, 0.8)):                       # drei Punkte im Feld (Innenbereich)
            px = at(im, (c[0] + c[2] * fx) / 100.0, (c[1] + c[3] * fy) / 100.0)
            check(near(px, RGB[nm]), f"{label}/{layout_id}: Feld {nm} an ({fx},{fy}) ist {tuple(px)} statt {RGB[nm]}")
    # Ränder der Felder: kein Grau vom Hauptvideo (Lückenfreiheit) – Punkte direkt an der Trennlinie beidseitig
    h, w = im.shape[:2]
    gray = np.abs(im - 128).max(axis=2) < 12
    check(gray.sum() == 0, f"{label}/{layout_id}: {int(gray.sum())} graue Bildpunkte (Lücken zwischen den Feldern)")


for lid in ("2h", "2v", "3l", "3c", "4"):
    pr = make_project()
    used = split.apply(pr, lid, sel=0)
    check(len(used) == len(split.layout(lid)[1]), lid)
    # Blöcke, die nicht im Split sind, dürfen nichts verdecken → ans Ende der Reihenfolge verschieben: hier einfach löschen
    pr.overlays = [pr.overlays[i] for i in used]
    im = frame(pr, f"split_{lid}")
    # Reihenfolge der Quellen entspricht der Reihenfolge der Blöcke
    global_order = [order[i] for i in used]
    order_backup = order[:]
    order[:] = global_order
    expect(im, lid, "Export")
    order[:] = order_backup
    print(f"OK  Export {lid}: {im.shape[1]}x{im.shape[0]}")

# ohne Split bleibt das Bild-in-Bild klein (Hauptvideo sichtbar)
pr = make_project()
pr.overlays = pr.overlays[:1]
im = frame(pr, "nosplit")
check(near(at(im, 0.2, 0.5), (128, 128, 128), 20), "ohne Feld darf das Bild-in-Bild nicht füllen")
print("OK  ohne Split unverändert")

# Hochformat-Quelle (blau) im Feld: füllt aus, keine schwarzen Balken
pr = make_project()
pr.overlays = [pr.overlays[2], pr.overlays[0]]
split.apply(pr, "2h", sel=0)
im = frame(pr, "portrait")
h, w = im.shape[:2]
left = im[:, : w // 2 - 2]
check(near(left.reshape(-1, 3).mean(axis=0), RGB["blue"], 25), f"Hochformat-Quelle füllt das Feld nicht: {left.reshape(-1, 3).mean(axis=0)}")
print("OK  Hochformat füllt das Feld")

# Zeitfenster: Block, der erst später beginnt, zeigt vorher das Hauptvideo
pr = make_project()
pr.overlays = pr.overlays[:2]
pr.overlays[1].start = 2.0
split.apply(pr, "2h", sel=0)
early, late = frame(pr, "early", 1.0), frame(pr, "late", 3.0)
check(near(at(early, 0.9, 0.5), (128, 128, 128), 20) and near(at(late, 0.9, 0.5), RGB["green"]), "Feld erscheint erst zu seiner Zeit")
print("OK  Zeitfenster")

# ---------------------------------------------------------------- Trennlinie
pr = make_project()
pr.overlays = pr.overlays[:2]
split.apply(pr, "2h", sel=0, gap=10.0, line="#000000")
check(all(o.cell_gap == 10.0 for o in pr.overlays), "Linie am Block gespeichert")
im = frame(pr, "gap")
check(near(at(im, 0.5, 0.5), (0, 0, 0), 25) and near(at(im, 0.53, 0.5), (0, 0, 0), 25) and near(at(im, 0.47, 0.5), (0, 0, 0), 25), "Trennlinie in der Mitte schwarz")
check(near(at(im, 0.01, 0.5), (0, 0, 0), 25) and near(at(im, 0.5, 0.01), (0, 0, 0), 25), "Linie auch um den Rand")
check(near(at(im, 0.3, 0.5), RGB["red"]) and near(at(im, 0.7, 0.5), RGB["green"]), "Felder daneben unverändert")
check(not near(at(im, 0.4, 0.5), (0, 0, 0), 60) and not near(at(im, 0.6, 0.5), (0, 0, 0), 60), "Linie nicht breiter als eingestellt")
pr.overlays[0].cell_line = pr.overlays[1].cell_line = "#ffffff"
im = frame(pr, "gap_white")
check(near(at(im, 0.5, 0.5), (255, 255, 255), 25), "weiße Linie")
pr.overlays[0].cell_line = "kaputt"
check(split.line_color(pr.overlays[0]) == "0x000000" and split.line_px(pr.overlays[0], 640) == 32, "kaputte Farbe wird schwarz")
check(split.line_px(OverlayClip("a.mp4", 1.0), 640) == 0 and split.line_px(OverlayClip("a.mp4", 1.0, cell_gap=float("nan")), 640) == 0, "ohne Linie")
print("OK  Trennlinie")

# ---------------------------------------------------------------- Bildausschnitt im Feld
half = tmp / "half.mp4"                # links rot, rechts blau
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x360:r=25:d=4", "-f", "lavfi", "-i", "color=c=blue:s=320x360:r=25:d=4",
                "-filter_complex", "[0:v][1:v]hstack,format=yuv444p", "-c:v", "libx264", "-pix_fmt", "yuv444p", str(half)], check=True)
hi = probe(str(half))


def half_project(**kw):
    q = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    q.clips = [Clip(str(base), binfo.duration, has_audio=True, width=binfo.width, height=binfo.height)]
    q.overlays = [OverlayClip(str(half), hi.duration, 0.0, hi.duration, start=0.0, **kw), OverlayClip(str(srcs["green"]), 4.0, 0.0, 4.0, start=0.0)]
    split.apply(q, "2h", sel=0)
    return q


def left_cell(im):
    return [at(im, fx, 0.5) for fx in (0.05, 0.15, 0.25, 0.35, 0.45)]


im = frame(half_project(), "z100")
cl = left_cell(im)
check(near(cl[0], RGB["red"]) and near(cl[4], RGB["blue"]), f"mittiger Ausschnitt zeigt rot|blau: {cl}")
im = frame(half_project(cell_zoom=200.0, cell_dx=-100.0), "z200l")
check(all(near(c, RGB["red"]) for c in left_cell(im)), f"Zoom 200, ganz links: {left_cell(im)}")
im = frame(half_project(cell_zoom=200.0, cell_dx=100.0), "z200r")
check(all(near(c, RGB["blue"]) for c in left_cell(im)), f"Zoom 200, ganz rechts: {left_cell(im)}")
im = frame(half_project(cell_zoom=200.0, cell_dx=0.0), "z200m")
check(near(left_cell(im)[0], RGB["red"]) and near(left_cell(im)[4], RGB["blue"]), "Zoom 200, mittig")
# Zoom wird begrenzt, kaputte Werte ändern nichts
check(split.crop_params(OverlayClip("a", 1, cell_zoom=9999), 100, 100)[:2] == (400, 400), "Zoom höchstens 400 %")
check(split.crop_params(OverlayClip("a", 1, cell_zoom=10), 100, 100)[:2] == (100, 100), "Zoom mindestens 100 %")
check(split.crop_params(OverlayClip("a", 1, cell_zoom=float("nan"), cell_dx="x"), 100, 100) == (100, 100, 0.0, 0.0), "kaputte Werte")
print("OK  Bildausschnitt im Feld")

# ---------------------------------------------------------------- Hauptvideo in einem Feld
pr = make_project()
pr.overlays = [pr.overlays[0], pr.overlays[1]]
pr.overlays[0].start = pr.overlays[1].start = 2.0
check(split.apply(pr, "2h", sel=0, main="first") == [0], "mit Hauptvideo braucht 2h nur einen Block")
check(pr.overlays[0].cell == [50, 0, 50, 100] and pr.overlays[0].main_cell == [0, 0, 50, 100] and not pr.overlays[1].cell, "Felder verteilt")
early, late = frame(pr, "main_early", 1.0), frame(pr, "main_late", 3.0)
check(near(at(early, 0.2, 0.5), (128, 128, 128), 20) and near(at(early, 0.8, 0.5), (128, 128, 128), 20), "vor dem Split: Hauptvideo im ganzen Bild")
check(near(at(late, 0.2, 0.5), (128, 128, 128), 20) and near(at(late, 0.8, 0.5), RGB["red"]), "im Split: Hauptvideo links, Block rechts")
pr2 = make_project()
pr2.overlays = pr2.overlays[:2]
split.apply(pr2, "3l", sel=0, main="last")
imm = frame(pr2, "main_last")
check(near(at(imm, 0.75, 0.8), (128, 128, 128), 20) and near(at(imm, 0.25, 0.5), RGB["red"]) and near(at(imm, 0.75, 0.25), RGB["green"]), "Hauptvideo im letzten Feld von „1 groß + 2“")
try:
    split.apply(make_project(), "2h", sel=0, main="mitte")
    check(False, "ungültige Angabe")
except split.SplitError:
    pass
try:
    q = make_project()
    q.overlays = q.overlays[:1]
    split.apply(q, "4", sel=0, main="first")
    check(False, "4er-Raster mit Hauptvideo braucht drei Blöcke")
except split.SplitError as e:
    check("Hauptvideo" in str(e), str(e))
# Linie um das Hauptfeld
pr = make_project()
pr.overlays = pr.overlays[:1]
split.apply(pr, "2h", sel=0, main="first", gap=10.0)
im = frame(pr, "main_gap")
check(near(at(im, 0.5, 0.5), (0, 0, 0), 25) and near(at(im, 0.01, 0.5), (0, 0, 0), 25) and near(at(im, 0.3, 0.5), (128, 128, 128), 20), "Linie auch um das Hauptfeld")
# Aufheben setzt alles zurück
split.clear(pr)
o = pr.overlays[0]
check(not o.cell and not o.main_cell and o.cell_gap == 0.0 and o.cell_zoom == 100.0, "Aufheben setzt Zusatzangaben zurück")
q = Project.from_json(Project(overlays=[OverlayClip("a.mp4", 5.0, cell=[0, 0, 50, 50], main_cell=[50, 0, 50, 50], cell_gap=3.0, cell_line="#ff0000", cell_zoom=150.0, cell_dx=-20.0)]).to_json())
oo = q.overlays[0]
check(oo.main_cell == [50, 0, 50, 50] and oo.cell_gap == 3.0 and oo.cell_line == "#ff0000" and oo.cell_zoom == 150.0 and oo.cell_dx == -20.0, "Speichern/Laden")
print("OK  Hauptvideo im Feld")

# Fenster-Projekt der Live-Vorschau enthält die Felder
pr = make_project()
split.apply(pr, "4", sel=0)
wp, off, ln = projwin.project_window(pr, 1.0, 2.0)
check(len(wp.overlays) == 4 and all(o.cell for o in wp.overlays), "Live-Fenster verliert die Felder")
print("OK  Live-Vorschau-Fenster")
print("ALLES OK")
