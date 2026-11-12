"""Keyframes für Bild-in-Bild: Position, Größe und Deckkraft über die Zeit des Blocks.

Ein Keyframe ist ein Wörterbuch ``{"t": 0..1, "x": %, "y": %, "size": %, "opacity": %}``;
``t`` ist die relative Zeit im Block (0 = Anfang, 1 = Ende).
"""
from __future__ import annotations

MAX_KEYS = 12
# Wertebereiche; x und y dürfen etwas außerhalb liegen (Block fährt aus dem Bild)
LIMITS = {"x": (-50.0, 150.0), "y": (-50.0, 150.0), "size": (5.0, 100.0), "opacity": (0.0, 100.0), "rot": (-720.0, 720.0)}
FIELDS = tuple(LIMITS)
MIN_GAP = 0.005          # kleinster Zeitabstand zweier Punkte


def _num(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) != float("inf") else default


def base_values(o) -> dict:
    """Die festen Werte eines Blocks – daraus entstehen fehlende Angaben in einem Keyframe."""
    return {"x": float(o.x_pct), "y": float(o.y_pct), "size": float(o.size_pct), "opacity": float(o.opacity),
            "rot": float(getattr(o, "rot", 0.0))}


def clean(keys, o=None) -> list[dict]:
    """Bereinigt eine Keyframe-Liste: nur Wörterbücher, Werte im Bereich, sortiert, ohne doppelte Zeiten, höchstens MAX_KEYS."""
    base = base_values(o) if o is not None else {"x": 75.0, "y": 25.0, "size": 35.0, "opacity": 100.0, "rot": 0.0}
    out: list[dict] = []
    for k in keys or []:
        if not isinstance(k, dict):
            continue
        item = {"t": max(0.0, min(1.0, _num(k.get("t"), 0.0)))}
        for f, (lo, hi) in LIMITS.items():
            item[f] = max(lo, min(hi, _num(k.get(f), base[f])))
        out.append(item)
    out.sort(key=lambda d: d["t"])
    res: list[dict] = []
    for item in out:
        if res and item["t"] - res[-1]["t"] < MIN_GAP:
            item["t"] = min(1.0, res[-1]["t"] + MIN_GAP)
            if item["t"] - res[-1]["t"] < MIN_GAP:      # am Ende angekommen: letzten Punkt behalten
                res[-1] = item
                continue
        res.append(item)
    return res[:MAX_KEYS]


def active(o) -> bool:
    """Hat der Block gültige Keyframes (mindestens zwei Punkte, kein Split-Feld)?"""
    if getattr(o, "cell", None):
        return False
    return len(clean(getattr(o, "keys", []), o)) >= 2


def add_key(o, t: float) -> int:
    """Fügt zur Zeit t einen Punkt mit dem aktuell berechneten Wert ein; gibt dessen Index zurück."""
    keys = clean(o.keys, o)
    if not keys:                       # erster Punkt: Anfangs- und Endpunkt aus den festen Werten
        keys = [dict(t=0.0, **base_values(o)), dict(t=1.0, **base_values(o))]
    t = max(0.0, min(1.0, float(t)))
    for i, k in enumerate(keys):       # schon ein Punkt in der Nähe: den wählen
        if abs(k["t"] - t) < 0.02:
            o.keys = keys
            return i
    if len(keys) >= MAX_KEYS:
        o.keys = keys
        return min(range(len(keys)), key=lambda i: abs(keys[i]["t"] - t))
    vals = value_at(keys, t)
    keys.append(dict(t=t, **vals))
    o.keys = clean(keys, o)
    return min(range(len(o.keys)), key=lambda i: abs(o.keys[i]["t"] - t))


def remove_key(o, index: int) -> bool:
    keys = clean(o.keys, o)
    if not (0 <= index < len(keys)):
        return False
    del keys[index]
    o.keys = keys if len(keys) >= 2 else []      # ein einzelner Punkt wäre sinnlos
    return True


def set_key(o, index: int, **vals) -> bool:
    """Ändert Werte (t, x, y, size, opacity) eines Punkts und bereinigt die Liste."""
    keys = clean(o.keys, o)
    if not (0 <= index < len(keys)):
        return False
    for f, v in vals.items():
        if f == "t" or f in LIMITS:
            keys[index][f] = _num(v, keys[index][f])
    o.keys = clean(keys, o)
    return True


def _smooth(u: float) -> float:
    return u * u * (3 - 2 * u)


def value_at(keys: list[dict], t: float, ease: bool = True) -> dict:
    """Werte zur relativen Zeit t (wie sie der Export rechnet)."""
    if not keys:
        return {}
    t = max(0.0, min(1.0, t))
    if t <= keys[0]["t"]:
        return {f: keys[0][f] for f in FIELDS}
    for a, b in zip(keys[:-1], keys[1:]):
        if t < b["t"]:
            u = (t - a["t"]) / max(b["t"] - a["t"], 1e-6)
            u = _smooth(u) if ease else u
            return {f: a[f] + (b[f] - a[f]) * u for f in FIELDS}
    return {f: keys[-1][f] for f in FIELDS}


# ---- Vorlagen (setzen nur Keyframes aus den festen Werten des Blocks) -------------------------------

PRESETS = {
    "in_left": "Von links hereinfahren",
    "in_right": "Von rechts hereinfahren",
    "zoom_up": "Hochzoomen",
    "fade_away": "Ausblenden",
    "swing": "Hin und her",
    "spin_in": "Reinwirbeln",
    "wobble": "Wackeln",
}


def preset_keys(name: str, o) -> list[dict]:
    b = base_values(o)
    full = lambda t, **kw: dict(t=t, **{**b, **kw})        # noqa: E731
    half = b["size"] / 2.0
    if name == "in_left":
        keys = [full(0.0, x=-half), full(0.3, x=b["x"]), full(1.0)]
    elif name == "in_right":
        keys = [full(0.0, x=100.0 + half), full(0.3, x=b["x"]), full(1.0)]
    elif name == "zoom_up":
        keys = [full(0.0, size=max(5.0, b["size"] * 0.2), opacity=0.0), full(0.35), full(1.0)]
    elif name == "fade_away":
        keys = [full(0.0), full(0.7), full(1.0, opacity=0.0)]
    elif name == "swing":
        keys = [full(0.0), full(0.5, x=100.0 - b["x"]), full(1.0)]
    elif name == "spin_in":
        keys = [full(0.0, size=max(5.0, b["size"] * 0.2), opacity=0.0, rot=b["rot"] - 360.0), full(0.4), full(1.0)]
    elif name == "wobble":
        r = b["rot"]
        keys = [full(0.0), full(0.2, rot=r - 10.0), full(0.4, rot=r + 10.0), full(0.6, rot=r - 6.0), full(0.8, rot=r + 6.0), full(1.0)]
    else:
        return []
    return clean(keys, o)


def apply_preset(name: str, o) -> bool:
    keys = preset_keys(name, o)
    if not keys:
        return False
    o.keys = keys
    return True
