"""Marker auf der Timeline: Punkte mit Zeit und Namen (Taste M), zum Springen, Einrasten und für Beat-Sync."""
from __future__ import annotations

from .project import Project

MAX_MARKERS = 500
MIN_GAP = 0.05          # zwei Marker näher als so viele Sekunden gelten als derselbe


def clean(markers, total: float | None = None) -> list[dict]:
    """Bereinigt eine Marker-Liste: nur Wörterbücher mit gültiger Zeit, sortiert, ohne Doppelte, höchstens MAX_MARKERS."""
    out: list[dict] = []
    for m in markers or []:
        if not isinstance(m, dict):
            continue
        try:
            t = float(m.get("t"))
        except (TypeError, ValueError):
            continue
        if t != t or t < 0 or t == float("inf"):
            continue
        if total is not None and total > 0:
            t = min(t, total)
        out.append({"t": round(t, 3), "name": str(m.get("name") or "")[:60]})
    out.sort(key=lambda d: d["t"])
    res: list[dict] = []
    for m in out:
        if res and m["t"] - res[-1]["t"] < MIN_GAP:
            continue
        res.append(m)
    return res[:MAX_MARKERS]


def times(project: Project) -> list[float]:
    return [m["t"] for m in project.markers]


def add(project: Project, t: float, name: str = "") -> int:
    """Setzt einen Marker; liegt schon einer in der Nähe, wird dessen Index zurückgegeben (und der Name ergänzt, wenn er leer war)."""
    t = max(0.0, float(t))
    for i, m in enumerate(project.markers):
        if abs(m["t"] - t) < MIN_GAP:
            if name and not m.get("name"):
                m["name"] = name[:60]
            return i
    if len(project.markers) >= MAX_MARKERS:
        return min(range(len(project.markers)), key=lambda i: abs(project.markers[i]["t"] - t))
    project.markers.append({"t": round(t, 3), "name": name[:60]})
    project.markers = clean(project.markers)
    return min(range(len(project.markers)), key=lambda i: abs(project.markers[i]["t"] - t))


def add_many(project: Project, ts, name: str = "") -> int:
    """Setzt viele Marker auf einmal (z. B. Beats); gibt die Zahl der neu angelegten zurück."""
    before = len(project.markers)
    merged = list(project.markers) + [{"t": float(t), "name": name} for t in ts]
    project.markers = clean(merged)
    return len(project.markers) - before


def nearest(project: Project, t: float, within: float = 0.25) -> int:
    best, dist = -1, within
    for i, m in enumerate(project.markers):
        if abs(m["t"] - t) <= dist:
            best, dist = i, abs(m["t"] - t)
    return best


def remove(project: Project, index: int) -> bool:
    if not 0 <= index < len(project.markers):
        return False
    del project.markers[index]
    return True


def rename(project: Project, index: int, name: str) -> bool:
    if not 0 <= index < len(project.markers):
        return False
    project.markers[index]["name"] = str(name)[:60]
    return True


def step(project: Project, t: float, direction: int) -> float | None:
    """Zeit des nächsten (direction > 0) oder vorherigen Markers; None, wenn keiner da ist."""
    ts = times(project)
    if direction > 0:
        c = [x for x in ts if x > t + 0.02]
        return min(c) if c else None
    c = [x for x in ts if x < t - 0.02]
    return max(c) if c else None


def clear(project: Project) -> int:
    n = len(project.markers)
    project.markers = []
    return n
