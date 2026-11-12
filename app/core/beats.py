"""Beat-Erkennung und Schnitt auf den Beat.

Aus dem Ton eines Audioblocks wird ein Verlauf „wo passiert etwas Neues“ (Spektralfluss) berechnet. Daraus ergeben sich Tempo (BPM)
und die Zeiten der Schläge. Die Schläge können als Marker auf die Timeline gesetzt werden; „Clips auf den Beat schneiden“ legt die
Schnitte zwischen den Clips auf diese Zeiten.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import numpy as np

from .. import paths
from .project import AudioClip, Project

SR = 11025                    # Analyse-Abtastrate
N_FFT = 512
DELAY = 0.78 * N_FFT / SR   # Der Spektralfluss steigt, sobald ein Schlag ins Analysefenster eintritt – etwas vor dem Schlag selbst
HOP = 128                     # ≈ 11,6 ms pro Schritt
LOW_WEIGHT = 3.0
MIN_BPM, MAX_BPM = 60.0, 190.0
MIN_SECONDS = 3.0
MAX_SECONDS = 600.0
MIN_CLIP = 0.3                # kürzere Clips entstehen beim Schnitt auf den Beat nicht
RELIABLE = 2.5                # darunter ist der Rhythmus schwach (Sprache, Ambient) – das Ergebnis ist unsicher


class BeatError(Exception):
    pass


@dataclass
class BeatResult:
    bpm: float
    beats: list[float] = field(default_factory=list)      # Sekunden ab Beginn des analysierten Abschnitts
    strength: float = 0.0                                   # Verhältnis Schlagstärke zu Durchschnitt; ≥ RELIABLE = verlässlich

    @property
    def reliable(self) -> bool:
        return self.strength >= RELIABLE


# ----------------------------------------------------------------------------------------------- Analyse
def decode(path: str, start: float = 0.0, length: float | None = None) -> np.ndarray:
    """Mono, 11025 Hz, als float-Feld (−1 … 1). Wirft BeatError, wenn kein Ton gelesen werden kann."""
    cmd = [paths.find_binary("ffmpeg"), "-v", "error", "-nostdin", "-ss", f"{max(0.0, start):.3f}"]
    if length:
        cmd += ["-t", f"{min(length, MAX_SECONDS):.3f}"]
    else:
        cmd += ["-t", f"{MAX_SECONDS:.0f}"]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or len(r.stdout) < 2:
        raise BeatError("Aus dieser Datei konnte kein Ton gelesen werden.")
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def onset_envelope(x: np.ndarray) -> np.ndarray:
    """Spektralfluss je Schritt (HOP), lokal bereinigt und auf Mittelwert 1 normiert. Index i entspricht der Zeit i·HOP/SR."""
    if len(x) < N_FFT * 2:
        raise BeatError("Der Abschnitt ist zu kurz für eine Beat-Erkennung.")
    n = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(N_FFT).astype(np.float32)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    hi = int(5000 * N_FFT / SR)
    mag = np.log1p(30.0 * mag[:, 2:hi])
    freq = (np.arange(2, hi) * SR / N_FFT)
    d = np.maximum(0.0, np.diff(mag, axis=0))
    low = d[:, freq < 300.0].sum(axis=1)
    high = d[:, freq >= 300.0].sum(axis=1)
    # beide Bereiche getrennt normieren: Bassdrum und Bass (tief) geben den Grundschlag, Becken und Gesang (hoch) sind breiter und sonst zu laut
    flux = LOW_WEIGHT * low / max(low.mean(), 1e-9) + high / max(high.mean(), 1e-9)
    flux = np.concatenate([[0.0], flux])
    k = int(0.5 * SR / HOP) | 1                      # lokalen Durchschnitt (0,5 s) abziehen: nur Spitzen bleiben
    local = np.convolve(flux, np.ones(k) / k, mode="same")
    env = np.maximum(0.0, flux - local)
    m = env.mean()
    return env / m if m > 1e-9 else env


def _score(env: np.ndarray, period: float, phase_steps: np.ndarray) -> tuple[float, float]:
    """Beste Phase (Sekunden) und mittlere Stärke an den Schlägen für eine Periode (Sekunden)."""
    step = HOP / SR
    n = len(env)
    total = (n - 1) * step
    ks = np.arange(0, int(total / period) + 1)
    t = phase_steps[:, None] + ks[None, :] * period                 # [Phasen, Schläge]
    valid = t <= total
    pos = np.where(valid, t / step, 0.0)
    i0 = np.minimum(pos.astype(int), n - 2)
    fr = pos - i0
    v = env[i0] * (1 - fr) + env[i0 + 1] * fr
    v = np.where(valid, v, 0.0)
    cnt = np.maximum(valid.sum(axis=1), 1)
    sc = v.sum(axis=1) / cnt
    b = int(np.argmax(sc))
    return float(phase_steps[b]), float(sc[b])


def _prior(bpm: float) -> float:
    """Sanfte Vorliebe für übliche Tempi (um 120 BPM); entscheidet bei Gleichstand zwischen halbem und doppeltem Tempo."""
    return float(np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.55) ** 2))


def analyze_samples(x: np.ndarray) -> BeatResult:
    env = onset_envelope(x)
    if env.max() < 1e-6 or np.count_nonzero(env > 1.0) < 4:
        raise BeatError("In dem Ton wurden keine Schläge gefunden (zu leise oder gleichmäßig).")
    env = np.convolve(env, np.array([0.25, 0.5, 0.25]), mode="same")      # kleine Toleranz für Zeitabweichungen von Schlägen
    step = HOP / SR
    total = (len(env) - 1) * step
    best = None
    for bpm in np.arange(MIN_BPM, MAX_BPM + 0.01, 0.5):               # grobe Suche
        period = 60.0 / bpm
        phases = np.arange(0.0, period, 0.012)
        ph, sc = _score(env, period, phases)
        w = sc * (0.6 + 0.4 * _prior(bpm))
        if best is None or w > best[0]:
            best = (w, period, ph, sc)
    _w, period, ph, sc = best
    for span, dt, dp in ((0.012, 0.0004, 0.004), (0.003, 0.0001, 0.002)):          # feine Suche um das Ergebnis
        cand = None
        for p in np.arange(period * (1 - span), period * (1 + span) + 1e-9, period * dt):
            phases = np.arange(max(0.0, ph - 0.03), ph + 0.03, dp)
            q, s = _score(env, float(p), phases)
            if cand is None or s > cand[2]:
                cand = (float(p), q, s)
        period, ph, sc = cand
    beats = []
    t = ph
    while t <= total + 1e-9:
        beats.append(t)
        t += period
    # jeden Schlag auf die nächste echte Spitze (±45 ms) ziehen, sonst beim Raster lassen
    snapped = []
    rad = int(0.045 / step)
    for b in beats:
        i = int(round(b / step))
        lo, hi = max(0, i - rad), min(len(env), i + rad + 1)
        if hi - lo > 2 and env[lo:hi].max() > 1.5:
            j = lo + int(np.argmax(env[lo:hi]))
            snapped.append(j * step)
        else:
            snapped.append(b)
    for i in range(1, len(snapped)):                              # Reihenfolge sichern
        if snapped[i] <= snapped[i - 1] + 0.05:
            snapped[i] = beats[i]
    base = float(np.mean(env))
    strength = sc / base if base > 0 else 0.0
    return BeatResult(bpm=round(60.0 / period, 2), beats=[round(float(b) + DELAY, 3) for b in snapped], strength=round(float(strength), 2))


def analyze_audio(clip: AudioClip) -> BeatResult:
    """Analysiert den genutzten Abschnitt (in_pt … out_pt) eines Audioblocks."""
    if clip.reverse:
        raise BeatError("Bei einem rückwärts laufenden Audioblock ist keine Beat-Erkennung möglich.")
    length = max(0.0, clip.out_pt - clip.in_pt)
    if length < MIN_SECONDS:
        raise BeatError(f"Der Audioblock ist zu kurz (mindestens {MIN_SECONDS:.0f} s).")
    return analyze_samples(decode(clip.path, clip.in_pt, length))


def to_project_times(clip: AudioClip, res: BeatResult, step: int = 1, offset: int = 0) -> list[float]:
    """Schläge als Zeiten auf der Timeline (Beginn des Blocks + Zeit/Tempo); `step` = jeder n-te Schlag, `offset` = ab dem wievielten."""
    out = []
    sp = max(0.01, clip.speed)
    for b in res.beats[max(0, offset)::max(1, int(step))]:
        t = clip.start + b / sp
        if t >= 0:
            out.append(round(t, 3))
    return out


def describe(res: BeatResult, step: int = 1) -> str:
    n = len(res.beats[::max(1, int(step))])
    text = f"Tempo: {res.bpm:.1f} BPM, {len(res.beats)} Schläge erkannt"
    if step > 1:
        text += f" – jeder {step}. ergibt {n} Marker/Schnittpunkte"
    if not res.reliable:
        text += "\nDer Rhythmus ist schwach (Sprache oder ruhige Musik?). Bitte die Marker prüfen."
    return text


# ----------------------------------------------------------------------------------------------- Schnitt
def snap_clips(project: Project, grid: list[float]) -> tuple[int, int]:
    """Legt die Schnitte zwischen den Clips auf die Zeiten in `grid` (Sekunden auf der Timeline) und kürzt/verlängert dafür das Ende
    jedes Clips. Clips mit Tempokurve bleiben unverändert. Gibt (geändert, übersprungen) zurück."""
    grid = sorted(g for g in grid if g > 0)
    if len(grid) < 2:
        raise BeatError("Es gibt zu wenige Beats für einen Schnitt.")
    changed = skipped = 0
    for i, c in enumerate(project.clips):
        if c.ramp_id:
            skipped += 1
            continue
        s = project.clip_start(i)
        tdur = project.overlap_after(i)
        cut = s + c.length - tdur
        for g in sorted(grid, key=lambda g: abs(g - cut)):
            if g - s < MIN_CLIP:
                continue
            new_len = g - s + tdur
            new_out = c.in_pt + new_len * max(c.speed, 0.01)
            if not c.is_image and new_out > c.duration + 1e-6:
                continue
            if abs(new_len - c.length) > 1e-6:
                c.out_pt = round(new_out, 4)
                changed += 1
            break
        else:
            skipped += 1
    for _ in range(3):                                   # Übergänge hängen von der Länge der Nachbarn ab: Feinabgleich
        moved = False
        for i, c in enumerate(project.clips[:-1]):
            if c.ramp_id:
                continue
            want = min(grid, key=lambda g: abs(g - project.clip_start(i + 1)))
            d = want - project.clip_start(i + 1)
            if 1e-4 < abs(d) < 0.2:
                out = c.in_pt + (c.length + d) * max(c.speed, 0.01)
                if c.is_image or out <= c.duration + 1e-6:
                    c.out_pt = round(out, 4)
                    moved = True
        if not moved:
            break
    project.sync_linked()
    return changed, skipped
