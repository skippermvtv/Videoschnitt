"""YouTube-Kapitel aus benannten Markern.

YouTube erkennt Kapitel in der Videobeschreibung, wenn die Liste bei 0:00 beginnt, mindestens drei Einträge hat und jedes
Kapitel mindestens 10 Sekunden lang ist. Nur Marker mit Namen werden Kapitel.
"""
from __future__ import annotations

from .project import Project

MIN_CHAPTERS = 3
MIN_LENGTH = 10.0


def fmt(t: float) -> str:
    """Zeit wie in YouTube-Kapiteln: m:ss, ab einer Stunde h:mm:ss (immer abgerundet auf ganze Sekunden)."""
    s = max(0, int(t))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def build(project: Project, intro: str = "Anfang") -> dict:
    """Gibt {"items": [(Sekunden, Name)], "text": str, "problems": [str], "notes": [str], "ok": bool} zurück.

    Liegt kein benannter Marker bei 0:00, wird vorn ein Kapitel `intro` ergänzt (YouTube verlangt 0:00) und das als Hinweis gemeldet."""
    total = project.duration
    raw: list[tuple[float, str]] = []
    unnamed = beyond = 0
    for m in project.markers:
        name = " ".join(str(m.get("name") or "").split())
        t = float(m.get("t", 0.0))
        if not name:
            unnamed += 1
        elif total > 0 and t >= total:
            beyond += 1
        else:
            raw.append((t, name))
    raw.sort(key=lambda x: x[0])              # nach echter Zeit, nicht nach Namen
    items: list[tuple[int, str]] = [(int(t), n) for t, n in raw]
    notes: list[str] = []
    if unnamed:
        notes.append(f"{unnamed} Marker ohne Namen werden nicht als Kapitel verwendet.")
    if beyond:
        notes.append(f"{beyond} Marker liegen hinter dem Ende des Videos und werden übersprungen.")
    if not items or items[0][0] > 0:
        items.insert(0, (0, (intro or "Anfang").strip() or "Anfang"))
        notes.append(f"Bei 0:00 fehlte ein Kapitel – „{items[0][1]}“ wurde ergänzt (YouTube verlangt das).")
    problems: list[str] = []
    seen: set[int] = set()
    dup = []
    for t, n in items:
        if t in seen:
            dup.append(fmt(t))
        seen.add(t)
    if dup:
        problems.append("Zwei Kapitel liegen in derselben Sekunde (" + ", ".join(dup) + ") – bitte einen Marker verschieben.")
    if len(items) < MIN_CHAPTERS:
        problems.append(f"YouTube braucht mindestens {MIN_CHAPTERS} Kapitel – es gibt erst {len(items)}.")
    short = []
    for k, (t, n) in enumerate(items):
        end = items[k + 1][0] if k + 1 < len(items) else total
        if total > 0 and end - t < MIN_LENGTH and not (t in dup):
            short.append(f"{fmt(t)} {n}")
    if short:
        problems.append(f"Kapitel kürzer als {int(MIN_LENGTH)} Sekunden: " + "; ".join(short) + ".")
    text = "\n".join(f"{fmt(t)} {n}" for t, n in items)
    return {"items": items, "text": text, "problems": problems, "notes": notes, "ok": not problems}
