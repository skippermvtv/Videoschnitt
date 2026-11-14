"""Text-Schnitt: Vorschläge aus Wortzeiten, Schneiden der Clips, Nachziehen der Untertitel (ohne Medien, reine Rechnung)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import textcut  # noqa: E402
from app.core.pieces import PieceError  # noqa: E402
from app.core.project import Clip, Project, SubtitleCue  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def cue(start, items):
    """items: [(Wort, relativer Beginn, relatives Ende)] → Untertitel mit Wortzeiten."""
    words = [[w, a, b] for w, a, b in items]
    return SubtitleCue(start, start + items[-1][2] + 0.1, " ".join(w for w, _, _ in items), words)


def make(speed2=1.0):
    p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
    p.clips = [Clip("/x/a.mp4", 60.0, in_pt=10.0, out_pt=30.0, has_audio=True, width=1920, height=1080),     # Timeline 0…20
               Clip("/x/b.mp4", 60.0, in_pt=0.0, out_pt=20.0, has_audio=True, width=1920, height=1080, speed=speed2)]
    p.subtitles = [
        cue(1.0, [("Also", 0.0, 0.3), ("ähm", 0.4, 0.8), ("ich", 1.0, 1.2), ("ich", 1.3, 1.5), ("denke,", 1.6, 2.0)]),
        cue(6.0, [("das", 0.0, 0.2), ("ist", 0.3, 0.5), ("gut.", 1.5, 1.9)]),                    # Pause 1,0 s zwischen „ist“ und „gut.“
        cue(14.0, [("Äh,", 0.0, 0.3), ("weiter", 0.4, 0.9)]),
        cue(22.0, [("zweiter", 0.0, 0.4), ("Clip", 0.5, 0.9), ("ähm", 1.0, 1.4), ("ja", 1.5, 1.7)]),
    ]
    return p


p = make()
words = textcut.words_of(p)
check(len(words) == 14 and words == sorted(words, key=lambda w: w.start), len(words))
check(abs(words[1].start - 1.4) < 1e-9, words[1])

# --- Vorschläge
fill = textcut.suggest(words, fillers=True, repeats=False)
check([c.label for c in fill] == ["ähm", "Äh,", "ähm"] and all(c.kind == "Füllwort" for c in fill), fill)
rep = textcut.suggest(words, fillers=False, repeats=True)
check(len(rep) == 1 and rep[0].kind == "Wiederholung" and abs(rep[0].start - 2.0) < 1e-9 and abs(rep[0].end - 2.3) < 1e-9, rep)
pau = textcut.suggest(words, fillers=False, repeats=False, pause=0.7)
check(any(c.kind == "Pause" and abs(c.length - 0.7) < 0.05 for c in pau), pau)   # 1,0 s Pause minus 2 × 0,15 s Rand
check(not textcut.suggest(words, fillers=False, repeats=False, pause=0.0), "Pausen aus")
big = [textcut.Word(0, 0, "a", 0.0, 0.5), textcut.Word(0, 1, "b", 9.0, 9.5)]
check(not textcut.suggest(big, fillers=False, repeats=False, pause=0.7), "sehr lange Lücke bleibt")
allc = textcut.suggest(words, pause=0.7)
check(len(allc) >= 5 and all(a.end <= b.start for a, b in zip(allc, allc[1:])), allc)
check("Schnitte" in textcut.describe(allc) and textcut.describe([]).startswith("Nichts"), textcut.describe(allc))
sel = textcut.from_words([words[2], words[3], words[9]])                        # „ich ich“ nebeneinander, „zweiter“ einzeln
check(len(sel) == 2 and sel[0].kind == "Auswahl" and sel[0].label == "ich ich", sel)
print("OK  Vorschläge")


# --- Anwenden: Quellzeit jedes behaltenen Worts bleibt gleich
def source_pos(proj, t):
    """Quellsekunde (Datei, Position) der Timeline-Zeit t."""
    starts = proj.clip_starts()
    for i in range(len(proj.clips) - 1, -1, -1):
        if t >= starts[i] - 1e-9:
            c = proj.clips[i]
            return c.path, c.in_pt + (t - starts[i]) * c.speed
    raise AssertionError(t)


for speed2 in (1.0, 2.0):
    p = make(speed2)
    ws = textcut.words_of(p)
    before = {(w.cue, w.idx): source_pos(p, (w.start + w.end) / 2) for w in ws}
    dur0 = p.duration
    cuts = textcut.suggest(ws, pause=0.7)
    res = textcut.apply(p, cuts)
    check(res["clips"] == 2 and not res["notes"], res)
    check(abs((dur0 - p.duration) - res["removed"]) < 1e-6, (dur0, p.duration, res))
    check(len(p.clips) > 2, "Clips wurden nicht geteilt")
    check(abs(sum(c.length for c in p.clips) - p.duration) < 1e-6, "Dauer passt nicht (keine Überblendungen)")
    texts = " ".join(c.text for c in p.subtitles)
    check("ähm" not in texts and "Äh," not in texts and texts.count("ich") == 1, texts)
    # jedes übrig gebliebene Wort liegt an derselben Stelle der Quelldatei wie vorher
    n = 0
    for c in p.subtitles:
        for w, a, b in c.words:
            mid = c.start + (a + b) / 2
            orig = [(k, v) for k, v in before.items() if True]
            n += 1
        check(c.end > c.start and abs(c.end - c.start) >= 0.1, c)
    check(n == 14 - 3 - 1, n)                                    # 3 Füllwörter, 1 doppeltes „ich“
    after = {}
    for ci, c in enumerate(p.subtitles):
        for w, a, b in c.words:
            after[w] = source_pos(p, c.start + (a + b) / 2)
    names = {(w.cue, w.idx): w.text for w in ws}
    for k, pos in before.items():
        t = names[k]
        if t in after and t not in ("ich",):
            check(after[t][0] == pos[0] and abs(after[t][1] - pos[1]) < 0.06, (t, pos, after[t], speed2))
print("OK  Anwenden (Tempo 1 und 2): Quellstellen bleiben gleich, Dauer und Untertitel passen")

# --- Sonderfälle
p = make()
p.clips[1].reverse = True
res = textcut.apply(p, textcut.suggest(textcut.words_of(p), pause=0.7))
check(res["clips"] == 1 and any("rückwärts" in n for n in res["notes"]), res)
p = make()
try:
    textcut.apply(p, [])
    check(False, "leere Schnittliste hätte scheitern müssen")
except PieceError:
    pass
p = make()
p.markers = [{"t": 7.0, "name": "Marke"}]
textcut.apply(p, [textcut.Cut(2.0, 4.0, "Auswahl", "x")])
check(abs(p.markers[0]["t"] - 5.0) < 1e-6, p.markers)
p = make()
p.subtitles = [SubtitleCue(3.0, 5.0, "ohne Wortzeiten", [])]
check(textcut.words_of(p) == [], "ohne Wortzeiten keine Wörter")
textcut.apply(p, [textcut.Cut(1.0, 2.0, "Auswahl", "x")])
check(abs(p.subtitles[0].start - 2.0) < 1e-6, p.subtitles[0])
print("OK  Sonderfälle")
print("ALLES OK")
