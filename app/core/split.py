"""Split Screen: mehrere Bild-in-Bild-Blöcke teilen sich das Bild in Felder (je Block ein Feld, das Bild füllt das Feld aus).

Ein Block mit `cell = [x, y, Breite, Höhe]` (in % des Bildes) wird im Export nicht als kleines Bild eingeblendet, sondern
auf dieses Feld zugeschnitten und exakt dort platziert. Die Felder eines Layouts schließen lückenlos aneinander an.
"""
from __future__ import annotations

import re

from .project import Project

MIN_OVERLAP = 0.05          # so lange (s) müssen Blöcke gleichzeitig laufen

# (Kennung, Name, Felder [x, y, Breite, Höhe] in %)
LAYOUTS: list[tuple[str, str, list[list[float]]]] = [
    ("2h", "2 nebeneinander", [[0, 0, 50, 100], [50, 0, 50, 100]]),
    ("2v", "2 übereinander", [[0, 0, 100, 50], [0, 50, 100, 50]]),
    ("3l", "1 groß + 2 klein", [[0, 0, 50, 100], [50, 0, 50, 50], [50, 50, 50, 50]]),
    ("3c", "3 nebeneinander", [[0, 0, 100 / 3, 100], [100 / 3, 0, 100 / 3, 100], [200 / 3, 0, 100 / 3, 100]]),
    ("4", "4er-Raster", [[0, 0, 50, 50], [50, 0, 50, 50], [0, 50, 50, 50], [50, 50, 50, 50]]),
]


class SplitError(Exception):
    pass


def layout(layout_id: str):
    for lid, name, cells in LAYOUTS:
        if lid == layout_id:
            return name, [list(c) for c in cells]
    raise SplitError(f"Unbekanntes Layout: {layout_id}")


def valid_cell(cell) -> tuple[float, float, float, float] | None:
    """Gültiges Feld als (x, y, w, h) – sonst None (kaputte Werte werden ignoriert)."""
    try:
        x, y, w, h = (float(v) for v in cell)
    except (TypeError, ValueError):
        return None
    if not all(v == v for v in (x, y, w, h)) or w < 1.0 or h < 1.0 or x < 0 or y < 0 or x + w > 100.5 or y + h > 100.5:
        return None
    return x, y, w, h


def cell_px(o, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Feld des Blocks in Bildpunkten (x, y, Breite, Höhe); benachbarte Felder lassen weder Lücke noch Überlappung."""
    c = valid_cell(getattr(o, "cell", None))
    if c is None:
        return None
    x, y, w, h = c
    x0, x1 = round(width * x / 100.0), round(width * (x + w) / 100.0)
    y0, y1 = round(height * y / 100.0), round(height * (y + h) / 100.0)
    x1, y1 = min(x1, width), min(y1, height)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1 - x0, y1 - y0


def line_color(o) -> str:
    """Farbe der Trennlinie als FFmpeg-Farbe (0xRRGGBB); Ungültiges wird schwarz."""
    c = str(getattr(o, "cell_line", "") or "")
    return "0x" + c[1:] if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "0x000000"


def line_px(o, width: int) -> int:
    """Dicke der Linie je Feldkante in Bildpunkten (zwei Kanten nebeneinander ergeben die eingestellte Gesamtbreite)."""
    try:
        g = float(getattr(o, "cell_gap", 0.0))
    except (TypeError, ValueError):
        return 0
    if not g == g or g <= 0.0:
        return 0
    return max(1, round(min(g, 20.0) / 100.0 * width / 2.0))


def crop_params(o, cw: int, ch: int) -> tuple[int, int, int, int]:
    """(Skalierbreite, Skalierhöhe, x, y) für den Bildausschnitt im Feld: Zoom ≥ 100 %, Verschiebung −100 … 100."""
    def num(v, default):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return default
        return v if v == v else default
    z = max(100.0, min(num(getattr(o, "cell_zoom", 100.0), 100.0), 400.0)) / 100.0
    dx = max(-100.0, min(100.0, num(getattr(o, "cell_dx", 0.0), 0.0)))
    dy = max(-100.0, min(100.0, num(getattr(o, "cell_dy", 0.0), 0.0)))
    return round(cw * z), round(ch * z), dx, dy


def main_cell_px(project: Project, total: float, width: int, height: int):
    """Feld des Hauptvideos mit Zeitfenster: (x, y, w, h, von, bis) – oder None, wenn kein Split eines hat."""
    users = [o for o in project.overlays if is_split(o) and valid_cell(getattr(o, "main_cell", None)) and o.start < total - 0.05]
    if not users:
        return None
    probe_o = type("C", (), {"cell": users[0].main_cell})()
    px = cell_px(probe_o, width, height)
    if px is None:
        return None
    t0 = min(o.start for o in users)
    t1 = min(total, max(o.start + o.length for o in users))
    return (*px, max(0.0, t0), t1)


def is_split(o) -> bool:
    return valid_cell(getattr(o, "cell", None)) is not None


def candidates(project: Project, sel: int = -1, t: float = 0.0) -> list[int]:
    """Blöcke, die zusammen in ein Split passen: gleichzeitig zum gewählten Block (oder zur Zeit t). Gewählter zuerst."""
    ovs = project.overlays
    if 0 <= sel < len(ovs):
        a0, a1 = ovs[sel].start, ovs[sel].start + ovs[sel].length
        rest = [i for i, o in enumerate(ovs) if i != sel and min(a1, o.start + o.length) - max(a0, o.start) > MIN_OVERLAP]
        return [sel] + rest
    return [i for i, o in enumerate(ovs) if o.start <= t < o.start + o.length]


def apply(project: Project, layout_id: str, sel: int = -1, t: float = 0.0, indices=None,
          gap: float | None = None, line: str | None = None, main: str = "") -> list[int]:
    """Weist den ersten Blöcken (siehe `candidates`, oder die ausdrücklich genannten `indices`) je ein Feld zu.

    gap/line: Trennlinie (% der Bildbreite, Farbe „#RRGGBB“). main = "first" oder "last": das Hauptvideo läuft im
    ersten bzw. letzten Feld, die Blöcke bekommen die übrigen – es braucht dann ein Bild-in-Bild weniger."""
    name, cells = layout(layout_id)
    if main not in ("", "first", "last"):
        raise SplitError(f"Unbekannte Angabe für das Hauptvideo: {main}")
    main_cell = []
    if main:
        main_cell = cells.pop(0 if main == "first" else -1)
    cand = [i for i in indices if 0 <= i < len(project.overlays)] if indices is not None else candidates(project, sel, t)
    if len(cand) < len(cells):
        extra = " (das Hauptvideo füllt ein Feld)" if main else ""
        raise SplitError(f"„{name}“ braucht {len(cells)} Bild-in-Bild-Blöcke zur selben Zeit{extra} – gefunden: {len(cand)}.")
    used = cand[:len(cells)]
    for i, c in zip(used, cells):
        o = project.overlays[i]
        o.cell = [round(v, 4) for v in c]
        o.main_cell = [round(v, 4) for v in main_cell]
        o.border = False
        if gap is not None:
            o.cell_gap = max(0.0, min(20.0, float(gap)))
        if line is not None and re.fullmatch(r"#[0-9a-fA-F]{6}", str(line)):
            o.cell_line = str(line)
    return used


def clear(project: Project, indices=None) -> int:
    """Hebt das Split auf (alle oder die genannten Blöcke); gibt die Anzahl geänderter Blöcke zurück."""
    n = 0
    for i, o in enumerate(project.overlays):
        if (indices is None or i in indices) and o.cell:
            o.cell, o.main_cell = [], []
            o.cell_gap, o.cell_zoom, o.cell_dx, o.cell_dy = 0.0, 100.0, 0.0, 0.0
            n += 1
    return n
