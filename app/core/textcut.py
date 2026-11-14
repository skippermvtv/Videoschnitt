"""Text-Schnitt: Aus den Wortzeiten der Spracherkennung Schnitte ableiten (Füllwörter, Wiederholungen, lange Pausen oder
von Hand gewählte Wörter), den Clip dort teilen und die Untertitel mit verschieben. Ohne Qt.

Alle Zeiten der Schnitte sind Zeiten auf der Timeline (Sekunden). Die Wortzeiten stehen in `SubtitleCue.words` relativ zum
Beginn des Untertitels (siehe core/subtitles.py); Untertitel ohne Wortzeiten werden nicht berücksichtigt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import pieces, silence
from .pieces import PieceError
from .project import Project

FILLERS = frozenset({"äh", "ähm", "ähem", "ehm", "eh", "öhm", "öh", "ahm", "hm", "hmm", "mhm", "mmh", "uh", "uhm", "um", "ää", "ääh",
                     "ähh", "ähmm", "ehhm"})
MIN_CUT = 0.08                # kürzere Schnitte lohnen sich nicht
DEFAULT_PAUSE = 0.7           # Pausen zwischen zwei Wörtern, ab dieser Länge (Sekunden)
DEFAULT_MAX_PAUSE = 4.0       # längere Lücken sind meist Absicht (Musik, Szene) und bleiben stehen
DEFAULT_PAD = 0.15            # so viel Pause bleibt vor und nach dem Gesprochenen stehen
MAX_REPEAT_GAP = 0.8          # Wiederholung nur, wenn zwischen den gleichen Wörtern höchstens so viel Zeit liegt
_PUNCT = re.compile(r"[^\wäöüß]+", re.IGNORECASE)


@dataclass
class Word:
    cue: int                  # Index des Untertitels
    idx: int                  # Index des Worts im Untertitel
    text: str
    start: float              # Timeline-Sekunden
    end: float


@dataclass
class Cut:
    start: float              # Timeline-Sekunden
    end: float
    kind: str                 # „Füllwort“, „Wiederholung“, „Pause“, „Auswahl“
    label: str = ""

    @property
    def length(self) -> float:
        return self.end - self.start


def norm(word: str) -> str:
    return _PUNCT.sub("", word.lower())


def words_of(project: Project) -> list[Word]:
    """Alle Wörter mit echten Zeiten, in zeitlicher Reihenfolge."""
    out: list[Word] = []
    for ci, cue in enumerate(project.subtitles):
        for wi, w in enumerate(cue.words or []):
            try:
                text, a, b = str(w[0]), float(w[1]), float(w[2])
            except (TypeError, ValueError, IndexError):
                continue
            if b < a:
                continue
            out.append(Word(ci, wi, text, cue.start + a, cue.start + b))
    out.sort(key=lambda x: (x.start, x.cue, x.idx))
    return out


def suggest(words: list[Word], fillers: bool = True, repeats: bool = True, pause: float = 0.0,
            max_pause: float = DEFAULT_MAX_PAUSE, pad: float = DEFAULT_PAD) -> list[Cut]:
    """Schnittvorschläge. `pause` = Mindestlänge einer Pause zwischen zwei Wörtern (0 = Pausen nicht schneiden)."""
    cuts: list[Cut] = []
    for i, w in enumerate(words):
        n = norm(w.text)
        if fillers and n in FILLERS:
            cuts.append(Cut(w.start, w.end, "Füllwort", w.text))
            continue
        nxt = words[i + 1] if i + 1 < len(words) else None
        if repeats and nxt is not None and len(n) >= 2 and n == norm(nxt.text) and nxt.start - w.end <= MAX_REPEAT_GAP:
            cuts.append(Cut(w.start, nxt.start, "Wiederholung", f"{w.text} {nxt.text}"))
    if pause > 0:
        for a, b in zip(words, words[1:]):
            gap = b.start - a.end
            if pause <= gap <= max_pause:
                s, e = a.end + pad, b.start - pad
                if e - s >= MIN_CUT:
                    cuts.append(Cut(s, e, "Pause", f"{gap:.1f} s Pause"))
    cuts = [c for c in cuts if c.length >= MIN_CUT or c.kind != "Pause"]
    return merge(cuts)


def from_words(selection: list[Word]) -> list[Cut]:
    """Von Hand gewählte Wörter: benachbarte Wörter werden zu einem Schnitt."""
    cuts = [Cut(w.start, w.end, "Auswahl", w.text) for w in sorted(selection, key=lambda x: x.start)]
    return merge(cuts, join_gap=0.35)


def merge(cuts: list[Cut], join_gap: float = 1e-6) -> list[Cut]:
    """Sortiert und verbindet überlappende (oder fast aneinanderstoßende) Schnitte."""
    out: list[Cut] = []
    for c in sorted(cuts, key=lambda x: (x.start, x.end)):
        if out and c.start <= out[-1].end + join_gap:
            last = out[-1]
            last.end = max(last.end, c.end)
            if c.kind != last.kind:
                last.kind = last.kind if last.kind == c.kind else "Mehrere"
            last.label = (last.label + " " + c.label).strip()
        else:
            out.append(Cut(c.start, c.end, c.kind, c.label))
    return out


def summary(cuts: list[Cut]) -> dict:
    kinds: dict[str, int] = {}
    for c in cuts:
        kinds[c.kind] = kinds.get(c.kind, 0) + 1
    return {"cuts": len(cuts), "removed": sum(c.length for c in cuts), "kinds": kinds}


def describe(cuts: list[Cut]) -> str:
    if not cuts:
        return "Nichts zu schneiden gefunden."
    s = summary(cuts)
    kinds = ", ".join(f"{n}× {k}" for k, n in s["kinds"].items())
    return f"{s['cuts']} Schnitte ({kinds}), zusammen {s['removed']:.1f} s weniger."


# ------------------------------------------------------------------ Anwenden
def _clip_regions(project: Project) -> list[tuple[float, float]]:
    """Der Bereich der Timeline, der zu jedem Clip gehört (bis zum Start des nächsten Clips; bei Überblendung ohne den Überlapp)."""
    starts = project.clip_starts()
    out = []
    for i, c in enumerate(project.clips):
        end = starts[i] + c.length - (project.overlap_after(i) if i + 1 < len(project.clips) else 0.0)
        out.append((starts[i], end))
    return out


def _complement(keeps: list[tuple[float, float]], a: float, b: float) -> list[tuple[float, float]]:
    out, pos = [], a
    for ka, kb in keeps:
        if ka > pos + 1e-9:
            out.append((pos, ka))
        pos = max(pos, kb)
    if b > pos + 1e-9:
        out.append((pos, b))
    return out


def shift_time(t: float, removed: list[tuple[float, float]]) -> float:
    """Neue Timeline-Zeit von `t`, nachdem die (sortierten) Bereiche `removed` herausgenommen wurden."""
    s = 0.0
    for a, b in removed:
        if t >= b:
            s += b - a
        elif t > a:
            s += t - a
            break
        else:
            break
    return t - s


def plan(project: Project, cuts: list[Cut]) -> tuple[dict[int, list[tuple[float, float]]], list[tuple[float, float]], list[str]]:
    """(Keep-Bereiche je Clip in Quell-Sekunden, tatsächlich entfernte Bereiche auf der Timeline, Hinweise zu übersprungenen Clips)."""
    regions = _clip_regions(project)
    cuts = merge(cuts)
    keeps_by_clip: dict[int, list[tuple[float, float]]] = {}
    removed: list[tuple[float, float]] = []
    notes: list[str] = []
    for i, (c, (rs, re_)) in enumerate(zip(project.clips, regions)):
        mine = [(max(x.start, rs), min(x.end, re_)) for x in cuts if x.end > rs and x.start < re_]
        mine = [(a, b) for a, b in mine if b - a > 1e-6]
        if not mine:
            continue
        reason = ("ist ein Standbild" if c.is_image else "gehört zu einer Tempokurve" if c.ramp_id
                  else "läuft rückwärts" if c.reverse else "")
        if reason:
            notes.append(f"Clip {i + 1} ({c.name or 'ohne Namen'}) {reason} und wurde nicht geschnitten.")
            continue
        sp = max(0.01, c.speed)
        src = [(c.in_pt + (a - rs) * sp, c.in_pt + (b - rs) * sp) for a, b in mine]
        keeps = silence.keeps(src, c.in_pt, c.out_pt)
        if not keeps:
            notes.append(f"Clip {i + 1} ({c.name or 'ohne Namen'}) bliebe leer und wurde nicht geschnitten.")
            continue
        if len(keeps) > pieces.MAX_PIECES:
            notes.append(f"Clip {i + 1} ({c.name or 'ohne Namen'}) bekäme {len(keeps)} Stücke (höchstens {pieces.MAX_PIECES}) und wurde nicht geschnitten.")
            continue
        keeps_by_clip[i] = keeps
        for a, b in _complement(keeps, c.in_pt, c.out_pt):
            removed.append((rs + (a - c.in_pt) / sp, rs + (b - c.in_pt) / sp))
    removed.sort()
    return keeps_by_clip, removed, notes


def retime_subtitles(project: Project, removed: list[tuple[float, float]]) -> None:
    """Zieht die entfernten Bereiche aus den Untertiteln heraus: Wörter im Schnitt entfallen, alles danach rückt auf."""
    if not removed:
        return

    def inside(t: float) -> bool:
        return any(a <= t < b for a, b in removed)

    new = []
    for cue in project.subtitles:
        if cue.words:
            kept = [(w, cue.start + float(w[1]), cue.start + float(w[2])) for w in cue.words]
            kept = [(w, a, b) for w, a, b in kept if not inside((a + b) / 2)]
            if not kept:
                continue
            first_is_first = kept[0][0] is cue.words[0]
            last_is_last = kept[-1][0] is cue.words[-1]
            s = shift_time(cue.start if first_is_first else kept[0][1], removed)
            e = shift_time(cue.end if last_is_last else kept[-1][2], removed)
            if e < s + 0.1:
                e = s + 0.1
            words = [[str(w[0]), round(max(0.0, shift_time(a, removed) - s), 3), round(max(0.0, shift_time(b, removed) - s), 3)] for w, a, b in kept]
            cue.start, cue.end, cue.words = round(s, 3), round(e, 3), words
            cue.text = " ".join(w[0] for w in words)
            new.append(cue)
        else:
            if all(inside(t) for t in (cue.start, (cue.start + cue.end) / 2, cue.end - 1e-3)):
                continue
            s, e = shift_time(cue.start, removed), shift_time(cue.end, removed)
            if e - s < 0.1:
                continue
            cue.start, cue.end = round(s, 3), round(e, 3)
            new.append(cue)
    project.subtitles = new
    for m in project.markers or []:
        if isinstance(m, dict) and "t" in m:
            m["t"] = round(shift_time(float(m["t"]), removed), 3)


def apply(project: Project, cuts: list[Cut]) -> dict:
    """Schneidet die Clips an den Schnitten (Stücke dazwischen bleiben) und zieht die Untertitel nach.
    Gibt {"removed": entfernte Sekunden, "clips": Anzahl geschnittener Clips, "notes": Hinweise} zurück."""
    keeps_by_clip, removed, notes = plan(project, cuts)
    if not keeps_by_clip:
        raise PieceError("Es gab nichts zu schneiden." + (" " + " ".join(notes) if notes else ""))
    done = 0
    for i in sorted(keeps_by_clip, reverse=True):          # von hinten, damit die Indizes davor gültig bleiben
        pieces.split_into(project, i, keeps_by_clip[i])
        done += 1
    retime_subtitles(project, removed)
    return {"removed": sum(b - a for a, b in removed), "clips": done, "notes": notes}
