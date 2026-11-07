"""Bild-in-Bild-Blöcke, die gleichzeitig laufen (z. B. beim Split), bekommen eigene Zeilen in der Timeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.project import OverlayClip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def ov(start, length, speed=1.0):
    return OverlayClip("x.mp4", 60.0, 0.0, length * speed, start=start, speed=speed)


p = Project()
check(p.overlay_rows() == [], "leer")
p.overlays = [ov(0, 4)]
check(p.overlay_rows() == [0], "einer")
p.overlays = [ov(0, 4), ov(4, 2), ov(6, 3)]
check(p.overlay_rows() == [0, 0, 0], f"hintereinander: eine Zeile {p.overlay_rows()}")
p.overlays = [ov(0, 4), ov(2, 4)]
check(p.overlay_rows() == [0, 1], f"überlappend: zwei Zeilen {p.overlay_rows()}")
p.overlays = [ov(0, 5), ov(0, 5), ov(0, 5)]
check(p.overlay_rows() == [0, 1, 2], f"drei gleichzeitig (Split) {p.overlay_rows()}")
p.overlays = [ov(0, 5)] * 5
check(max(p.overlay_rows(3)) == 2 and p.overlay_rows(3)[:3] == [0, 1, 2], f"höchstens 3 Zeilen {p.overlay_rows(3)}")
check(max(p.overlay_rows(5)) == 4, "max_rows lässt sich ändern")
# Reihenfolge in der Liste ist egal: Zeile nach Startzeit, Gleichstand nach Listenposition
p.overlays = [ov(5, 3), ov(0, 6), ov(7, 2)]
check(p.overlay_rows() == [1, 0, 0] or p.overlay_rows() == [1, 0, 1], f"unsortierte Liste {p.overlay_rows()}")
check(p.overlay_rows()[1] == 0, "frühester Block liegt oben")
# Tempo verändert die Länge: bei 2-fachem Tempo ist der Block halb so lang und kollidiert nicht mehr
p.overlays = [ov(0, 4), ov(3, 2)]
check(p.overlay_rows() == [0, 1], "Kollision 3 < 4")
p.overlays = [OverlayClip("x.mp4", 60.0, 0.0, 8.0, start=0.0, speed=2.0), ov(4.5, 2)]
check(abs(p.overlays[0].length - 4.0) < 1e-9 and p.overlay_rows() == [0, 0], f"mit Tempo {p.overlay_rows()}")
# knapp aneinander (Rundung) gilt nicht als Überlappung
p.overlays = [ov(0, 4), ov(4.0000001, 2)]
check(p.overlay_rows() == [0, 0], "exakt aneinander")
print("OK  Zeilen für Bild-in-Bild")
print("ALLES OK")
