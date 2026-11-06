"""Kurven-Editor (Rechenkern): Umrechnung Pixel ↔ Kurve, Treffer, Ziehen, Hinzufügen, Entfernen."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import rampgraph as g  # noqa: E402
from app.core import speedramp as sr  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


W, H = 400.0, 200.0
# Achse: logarithmisch, ×1 liegt gleich weit über ×0,5 wie ×2 über ×1
d1 = g.speed_to_v(1) - g.speed_to_v(0.5)
d2 = g.speed_to_v(2) - g.speed_to_v(1)
check(abs(d1 - d2) < 1e-9, "Achse nicht logarithmisch")
check(g.speed_to_v(0.1) == 0.0 and abs(g.speed_to_v(8) - 1.0) < 1e-9, "Achsenenden")
for s in (0.1, 0.25, 0.7, 1, 3.3, 8):
    check(abs(g.v_to_speed(g.speed_to_v(s)) - s) < 1e-9, f"Hin- und Rückrechnung {s}")
check(g.v_to_speed(-5) == g.v_to_speed(0) and abs(g.v_to_speed(9) - 8) < 1e-9, "Begrenzung")
print("OK  Achse")

# Pixel
for pt in ([0, 1], [50, 0.25], [100, 8], [33.3, 0.1]):
    x, y = g.to_px(pt, W, H)
    pos, sp = g.from_px(x, y, W, H)
    check(abs(pos - pt[0]) < 1e-6 and abs(sp - pt[1]) < 1e-6, f"Pixel-Rundreise {pt}")
pos, sp = g.from_px(-50, -50, W, H)
check(pos == 0.0 and abs(sp - 8) < 1e-9, "außerhalb links oben wird begrenzt")
pos, sp = g.from_px(900, 900, W, H)
check(pos == 100.0 and abs(sp - 0.1) < 1e-9, "außerhalb rechts unten wird begrenzt")
print("OK  Pixel")

pts = [[0, 1], [50, 0.25], [100, 1]]
x, y = g.to_px(pts[1], W, H)
check(g.hit(pts, x + 3, y - 3, W, H) == 1, "Treffer auf Mittelpunkt")
check(g.hit(pts, x + 40, y, W, H) == -1, "kein Treffer weit daneben")
check(g.hit(pts, 1, g.to_px(pts[0], W, H)[1], W, H) == 0, "Treffer am Anfang")
print("OK  Treffer")

# Ziehen
m = g.move(pts, 1, 70, 2.0)
check(m[1] == [70, 2.0] and m[0] == [0, 1] and m[2] == [100, 1], f"Mittelpunkt ziehen {m}")
m = g.move(pts, 1, 120, 2.0)
check(m[1][0] == 99.0, "kann den Endpunkt nicht überholen")
m = g.move(pts, 1, -10, 99)
check(m[1][0] == 1.0 and m[1][1] == 8.0, f"Begrenzung beim Ziehen {m[1]}")
m = g.move(pts, 0, 40, 3)
check(m[0] == [0.0, 3.0], "Anfangspunkt bleibt bei 0 %")
m = g.move(pts, 2, 10, 0.01)
check(m[2] == [100.0, 0.1], "Endpunkt bleibt bei 100 %")
check(pts == [[0, 1], [50, 0.25], [100, 1]], "Original unverändert")
print("OK  Ziehen")

# Hinzufügen / Entfernen
new, i = g.add(pts, 25, 2)
check(i == 1 and len(new) == 4 and new[1] == [25, 2], f"Punkt einfügen {new}")
new2, i2 = g.add(pts, 50.4, 2)
check(i2 == -1 and new2 == pts, "zu nah an anderem Punkt")
check(g.add(pts, 0, 2)[1] == -1 and g.add(pts, 100, 2)[1] == -1, "nicht auf den Enden")
many = [[float(k * 8), 1.0] for k in range(13)]
many[-1][0] = 96.0
check(len(many) == g.MAX_POINTS + 1 and g.add(many[:g.MAX_POINTS], 97.5, 1)[1] == -1, "Obergrenze der Punkte")
check(g.remove(pts, 1) == [[0, 1], [100, 1]], "Mittelpunkt entfernen")
check(g.remove(pts, 0) == pts and g.remove(pts, 2) == pts, "Enden bleiben")
check(g.remove([[0, 1], [100, 1]], 1) == [[0, 1], [100, 1]], "mindestens zwei Punkte")
print("OK  Hinzufügen/Entfernen")

# Ergebnis wird von der Kurven-Logik akzeptiert und Zeichenzug stimmt mit speed_at überein
for p in (pts, new, g.move(pts, 1, 70, 8.0)):
    norm = sr.normalize(g.rounded(p))
    check(sr.format_points(norm), "formatierbar")
    check(len(sr.parse_points(sr.format_points(norm))) == len(norm), "Text-Rundreise")
line = g.polyline(pts, W, H)
check(len(line) == 121 and abs(line[0][0]) < 1e-9 and abs(line[-1][0] - W) < 1e-9, "Zeichenzug Länge")
x, y = line[60]
check(abs(g.from_px(x, y, W, H)[1] - sr.speed_at(pts, 0.5)) < 1e-6, "Zeichenzug folgt speed_at")
print("OK  Kurve")
print("ALLES OK")
