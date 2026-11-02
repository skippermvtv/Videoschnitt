"""Rechenteil der Farbwerkzeuge (Farbrad, Kurvenpunkte, Spline) – ohne Fenster; der Spline wird gegen FFmpeg geprüft."""
import math
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:                      # lokal ohne Qt: Attrappen, damit das Modul importierbar ist
    class _Dummy:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, n):
            return _Dummy()

    for name in ("PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"):
        m = types.ModuleType(name)
        m.__getattr__ = lambda n: _Dummy if n[0].isupper() else (_ for _ in ()).throw(AttributeError(n))
        sys.modules[name] = m
    sys.modules["PySide6.QtCore"].Signal = lambda *a, **k: _Dummy()

from app.core import grade  # noqa: E402
from app.paths import find_binary  # noqa: E402
from app.ui import colorwidgets as cw  # noqa: E402


def main() -> int:
    # Farbrad: Richtungen und Rückrechnung
    assert cw.rgb_from_xy(0, 0) == (0, 0, 0)
    r, g, b = cw.rgb_from_xy(1, 0)
    assert r == 100 and g == -50 and b == -50, (r, g, b)                      # rechts = Rot
    r, g, b = cw.rgb_from_xy(math.cos(math.radians(120)), math.sin(math.radians(120)))
    assert g == 100 and r == -50 and b == -50, (r, g, b)                      # oben links = Grün
    r, g, b = cw.rgb_from_xy(math.cos(math.radians(240)), math.sin(math.radians(240)))
    assert b == 100, (r, g, b)                                                # unten links = Blau
    assert cw.rgb_from_xy(5, 0) == (100, -50, -50), "außerhalb des Rands wird begrenzt"
    for k in range(360):
        for s in (0.1, 0.5, 1.0):
            x, y = s * math.cos(math.radians(k)), s * math.sin(math.radians(k))
            r, g, b = cw.rgb_from_xy(x, y)
            assert abs(r + g + b) <= 2                                        # neutral im Mittel
            x2, y2 = cw.xy_from_rgb(r, g, b)
            assert math.hypot(x - x2, y - y2) < 0.02, (k, s)
    assert math.hypot(*cw.xy_from_rgb(100, 100, 100)) <= 1.0 + 1e-9
    print("OK  Farbrad: Richtung, Radius, Rückrechnung")

    # Kurvenpunkte
    pts = [[0.0, 0.0], [1.0, 1.0]]
    i = cw.add_point(pts, 0.5, 0.7)
    assert i == 1 and pts == [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]
    assert cw.add_point(pts, 0.51, 0.2) == -1, "zu nah an vorhandenem Punkt"
    cw.move_point(pts, 1, 5.0, 2.0)                       # begrenzt auf Nachbarn und 0…1
    assert pts[1] == [0.98, 1.0], pts
    cw.move_point(pts, 0, 0.4, 0.3)
    assert pts[0] == [0.0, 0.3], "Randpunkt behält x"
    cw.move_point(pts, 2, 0.2, -1)
    assert pts[2] == [1.0, 0.0]
    assert not cw.remove_point(pts, 0) and not cw.remove_point(pts, 2) and cw.remove_point(pts, 1) and len(pts) == 2
    full = [[i / 11, i / 11] for i in range(12)]
    assert cw.add_point(full, 0.043, 0.5) == -1, "Höchstzahl an Punkten"
    pts = [[0, 0], [0.5, 0.5], [1, 1]]
    assert cw.nearest_point(pts, 0.52, 0.49, 0.05, 0.05) == 1 and cw.nearest_point(pts, 0.3, 0.9, 0.05, 0.05) == -1
    print("OK  Kurvenpunkte hinzufügen, verschieben, löschen, finden")

    # Der gezeichnete Spline stimmt mit FFmpegs curves-Filter überein
    ff = find_binary("ffmpeg")
    tmp = Path(tempfile.mkdtemp())
    for name, points in (("s", [[0, 0], [0.25, 0.1], [0.75, 0.9], [1, 1]]),
                         ("u", [[0, 0.1], [0.4, 0.7], [1, 0.8]]),
                         ("w", [[0, 0], [0.2, 0.4], [0.5, 0.3], [0.8, 0.9], [1, 1]])):
        sp = dict(cw.spline(points, 256))
        for level in (0x20, 0x60, 0xA0, 0xE0):
            src = tmp / "s.png"
            subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x{level:02x}{level:02x}{level:02x}:s=16x16",
                            "-vf", f"curves=master='{grade._curve_arg(points)}'", "-frames:v", "1", str(src)], check=True)
            got = int(np.array(Image.open(src).convert("RGB"))[4, 4, 0])
            x = level / 255.0
            want = np.interp(x, list(sp.keys()), list(sp.values())) * 255.0
            assert abs(got - want) <= 6, (name, level, got, want)
    print("OK  Spline der Anzeige = Ergebnis von FFmpeg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
