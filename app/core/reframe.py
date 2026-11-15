"""Auto-Hochkant: Querformat-Clips fürs Hochformat (9:16) so zuschneiden, dass der Bildausschnitt dem Geschehen folgt. Ohne Qt.

Es gibt keine Gesichts- oder Personenerkennung. Pro Bild wird geschätzt, wo „etwas los“ ist (Bewegung und Kontrast je Spalte);
das Fenster in der Breite des Zielformats sucht sich die Stelle mit der höchsten Summe. Danach wird die Kamerafahrt beruhigt:
kleine Abweichungen werden ignoriert, die Geschwindigkeit ist begrenzt, am Ende bleiben wenige Keyframes.

Das Ergebnis steht in `Clip.reframe` – Keyframes wie bei der Bewegung (`t` 0…1 über die Clip-Länge, `x` −100…100 = Fenster ganz links … ganz
rechts) – und wirkt im Layout „Füllen“ (siehe exporter._layout_chain).
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

from ..paths import find_binary
from .project import Clip, Project

_NOWINDOW = 0x08000000 if os.name == "nt" else 0

GRID_W, GRID_H = 192, 108          # Auswertungsraster (Graustufen)
SAMPLE_FPS = 5.0
MAX_KEYS = 24
MAX_SECONDS = 600.0                # längere Clips werden nur bis hierhin ausgewertet (Rest bleibt in der Mitte)
STYLES = {                         # Name: (Totzone in Bildbreiten, größte Geschwindigkeit in Bildbreiten pro Sekunde, Glättung)
    "ruhig": (0.12, 0.10, 0.85),
    "normal": (0.07, 0.22, 0.70),
    "lebhaft": (0.03, 0.45, 0.50),
}
DEFAULT_STYLE = "normal"


class ReframeError(Exception):
    pass


def target_aspect(project: Project) -> float:
    """Breite / Höhe des Projektformats."""
    from . import presets
    fmt = next((f for f in presets.load("formats") if f["id"] == project.format_id), None)
    if not fmt:
        return 9 / 16
    return max(0.1, float(fmt["width"]) / max(1.0, float(fmt["height"])))


def visible_aspect(c: Clip) -> float:
    """Seitenverhältnis des Clips nach Zuschnitt und Drehung (so, wie er ins Layout kommt)."""
    w, h = float(c.width or 16), float(c.height or 9)
    w *= 1.0 - (c.crop_l + c.crop_r) / 100.0
    h *= 1.0 - (c.crop_t + c.crop_b) / 100.0
    if c.rotate % 180:
        w, h = h, w
    return max(0.1, w) / max(0.1, h)


def window_fraction(c: Clip, aspect: float) -> float:
    """Anteil der Bildbreite, den das Zielformat zeigt (1.0 = ganzes Bild, es gibt nichts zu verschieben)."""
    return max(0.05, min(1.0, aspect / visible_aspect(c)))


def applicable(c: Clip, aspect: float) -> str:
    """Leer, wenn Auto-Hochkant für den Clip sinnvoll ist, sonst der Grund."""
    if c.is_image:
        return "ist ein Standbild"
    if c.ramp_id:
        return "gehört zu einer Tempokurve"
    if window_fraction(c, aspect) > 0.97:
        return "ist schon (fast) so breit wie das Format – es gibt nichts zu verschieben"
    return ""


# ---------------------------------------------------------------- Bilder lesen
def _transform_chain(c: Clip) -> str:
    from .exporter import _transform_chain as tc
    return tc(c)


def read_clip_frames(c: Clip, fps: float = SAMPLE_FPS, should_cancel: Callable[[], bool] | None = None):
    """Graustufen-Bilder (n, GRID_H, GRID_W) des Clip-Ausschnitts [in_pt, out_pt] mit Zuschnitt/Drehung/Spiegeln."""
    import numpy as np
    span = min(MAX_SECONDS, max(0.1, c.out_pt - c.in_pt))
    chain = _transform_chain(c)
    vf = (chain + "," if chain else "") + f"fps={fps:g},scale={GRID_W}:{GRID_H}:flags=area,format=gray"
    cmd = [find_binary("ffmpeg"), "-v", "error", "-ss", f"{c.in_pt:.3f}", "-t", f"{span:.3f}", "-i", c.path, "-an", "-sn",
           "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NOWINDOW)
    chunks: list[bytes] = []
    size = GRID_W * GRID_H
    try:
        assert proc.stdout is not None
        while True:
            if should_cancel and should_cancel():
                proc.kill()
                raise ReframeError("Abgebrochen.")
            buf = proc.stdout.read(size * 64)
            if not buf:
                break
            chunks.append(buf)
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    data = np.frombuffer(b"".join(chunks), dtype=np.uint8)
    n = data.size // size
    if proc.returncode not in (0, None) and n == 0:
        raise ReframeError(err.strip()[-300:] or "Bilder lesen fehlgeschlagen")
    if n < 2:
        raise ReframeError("Zu wenige Bilder zum Auswerten.")
    return data[: n * size].reshape(n, GRID_H, GRID_W)


# ---------------------------------------------------------------- Bewertung
def column_scores(frames):
    """Interesse je Bild und Spalte, Form (n, GRID_W): Bewegung (Differenz zum vorigen Bild) + Kantenkontrast, jeweils je Bild auf 0…1 normiert."""
    import numpy as np
    f = frames.astype(np.float32)
    n = len(f)
    motion = np.zeros_like(f)
    motion[1:] = np.abs(f[1:] - f[:-1])
    motion[0] = motion[1]
    gx = np.zeros_like(f)
    gx[:, :, 1:-1] = np.abs(f[:, :, 2:] - f[:, :, :-2])
    gy = np.zeros_like(f)
    gy[:, 1:-1, :] = np.abs(f[:, 2:, :] - f[:, :-2, :])
    edge = gx + gy
    # Mitte des Bildes zählt etwas mehr als Rand und Boden (dort liegen oft Einblendungen, Himmel/Boden sind selten das Motiv)
    ys = np.linspace(0, 1, f.shape[1], dtype=np.float32)
    vweight = (1.15 - 0.6 * np.abs(ys - 0.45))[None, :, None]
    col_m = (motion * vweight).sum(axis=1)
    col_e = (edge * vweight).sum(axis=1)
    out = np.zeros((n, f.shape[2]), dtype=np.float32)
    for i in range(n):
        m, e = col_m[i], col_e[i]
        mm, ee = float(m.max()), float(e.max())
        out[i] = (0.65 * m / mm if mm > 1e-6 else 0.0) + (0.35 * e / ee if ee > 1e-6 else 0.0)
    return out


def best_centers(scores, win: float):
    """Je Bild die Mitte (0…1 der Bildbreite) des Fensters der Breite `win` mit der höchsten Summe; ohne Inhalt: 0.5."""
    import numpy as np
    n, w = scores.shape
    k = max(1, int(round(win * w)))
    csum = np.concatenate([np.zeros((n, 1), dtype=np.float32), np.cumsum(scores, axis=1)], axis=1)
    sums = csum[:, k:] - csum[:, :-k]                       # (n, w-k+1)
    starts = np.argmax(sums, axis=1)
    # bei fast gleichwertigen Fenstern die Mitte bevorzugen (ruhiger)
    mid = (w - k) / 2.0
    best = sums[np.arange(n), starts]
    centre_val = sums[np.arange(n), int(round(mid)) if sums.shape[1] > 1 else 0]
    starts = np.where(centre_val >= best * 0.97, int(round(mid)), starts)
    centers = (starts + k / 2.0) / w
    flat = scores.max(axis=1) < 1e-6
    centers = np.where(flat, 0.5, centers)
    return centers.astype(np.float64)


def camera_path(centers, win: float, fps: float, style: str = DEFAULT_STYLE):
    """Beruhigte Kamerafahrt: Liste der Fenster-Mitten (0…1) je Bild. Totzone, begrenzte Geschwindigkeit, Glättung."""
    dead, vmax, smooth = STYLES.get(style, STYLES[DEFAULT_STYLE])
    lo, hi = win / 2.0, 1.0 - win / 2.0
    c = [float(x) for x in centers]
    # Mittelwert über 3 Bilder gegen Ausreißer (ein Bild mit Bewegungsrauschen)
    med = [sorted(c[max(0, i - 1):i + 2])[len(c[max(0, i - 1):i + 2]) // 2] for i in range(len(c))]
    cam = min(hi, max(lo, med[0]))
    out = [cam]
    step = vmax / fps
    for target in med[1:]:
        target = min(hi, max(lo, target))
        if abs(target - cam) > dead:
            want = cam + (target - cam) * (1.0 - smooth)
            delta = max(-step, min(step, want - cam))
            cam += delta
        out.append(min(hi, max(lo, cam)))
    return out


def _rdp(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    best, idx = -1.0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        yi = y0 + (y1 - y0) * ((x - x0) / (x1 - x0) if x1 != x0 else 0.0)
        d = abs(y - yi)
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [points[0], points[-1]]
    return _rdp(points[: idx + 1], tol)[:-1] + _rdp(points[idx:], tol)


def to_keys(path: list[float], win: float, reverse: bool = False) -> list[dict]:
    """Kamerafahrt (Mitten 0…1 je Bild) → Keyframes {"t": 0…1, "x": −100…100}, höchstens MAX_KEYS."""
    n = len(path)
    if n == 0:
        return []
    free = max(1e-6, 1.0 - win)
    offs = [min(1.0, max(0.0, (c - win / 2.0) / free)) for c in path]       # 0 = ganz links, 1 = ganz rechts
    if reverse:
        offs = offs[::-1]
    pts = [(i / (n - 1) if n > 1 else 0.0, o) for i, o in enumerate(offs)]
    tol = 0.01
    keys = _rdp(pts, tol)
    while len(keys) > MAX_KEYS:
        tol *= 1.5
        keys = _rdp(pts, tol)
    return [{"t": round(t, 4), "x": round((o * 2.0 - 1.0) * 100.0, 2)} for t, o in keys]


def analyze_clip(c: Clip, aspect: float, style: str = DEFAULT_STYLE,
                 should_cancel: Callable[[], bool] | None = None) -> list[dict]:
    """Keyframes für einen Clip (leere Liste: Fenster bleibt in der Mitte)."""
    why = applicable(c, aspect)
    if why:
        raise ReframeError(why)
    frames = read_clip_frames(c, SAMPLE_FPS, should_cancel)
    win = window_fraction(c, aspect)
    centers = best_centers(column_scores(frames), win)
    path = camera_path(centers, win, SAMPLE_FPS, style)
    keys = to_keys(path, win, reverse=c.reverse)
    if len(keys) >= 2 and max(abs(k["x"]) for k in keys) < 3.0:        # praktisch immer in der Mitte
        return []
    return keys


def analyze_project(project: Project, indices: list[int], style: str = DEFAULT_STYLE,
                    should_cancel: Callable[[], bool] | None = None,
                    on_progress: Callable[[float], None] | None = None) -> tuple[dict[int, list[dict]], list[str]]:
    """({Clip-Nr.: Keyframes}, Hinweise zu übersprungenen Clips)."""
    aspect = target_aspect(project)
    res: dict[int, list[dict]] = {}
    notes: list[str] = []
    todo = [i for i in indices if 0 <= i < len(project.clips)]
    for k, i in enumerate(todo):
        c = project.clips[i]
        why = applicable(c, aspect)
        if why:
            notes.append(f"Clip {i + 1} ({c.name or 'ohne Namen'}) {why}.")
        else:
            try:
                res[i] = analyze_clip(c, aspect, style, should_cancel)
            except ReframeError as exc:
                if str(exc) == "Abgebrochen.":
                    raise
                notes.append(f"Clip {i + 1} ({c.name or 'ohne Namen'}): {exc}")
        if on_progress:
            on_progress((k + 1) / len(todo))
    return res, notes


def apply(project: Project, result: dict[int, list[dict]], set_fill: bool = True) -> int:
    """Schreibt die Keyframes in die Clips (leere Liste = Reframe entfernen) und stellt das Layout auf „Füllen“. Gibt die Zahl der Clips zurück."""
    n = 0
    for i, keys in result.items():
        if 0 <= i < len(project.clips):
            project.clips[i].reframe = list(keys)
            n += 1
    if set_fill and n:
        project.layout = "fill"
    return n


def clear(project: Project, indices: list[int] | None = None) -> int:
    n = 0
    for i, c in enumerate(project.clips):
        if (indices is None or i in indices) and c.reframe:
            c.reframe = []
            n += 1
    return n
