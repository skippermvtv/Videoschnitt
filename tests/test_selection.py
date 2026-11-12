"""Mehrfachauswahl: gemeinsam löschen, duplizieren, verschieben (Projektdaten)."""
import os
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import selection as sel  # noqa: E402
from app.core.project import AudioClip, Clip, OverlayClip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def proj():
    p = Project()
    p.clips = [Clip(f"{n}.mp4", 10.0, 0.0, 4.0, has_audio=True) for n in "abcd"]           # 16 s
    p.audio_clips = [AudioClip("m1.wav", 20.0, 0.0, 6.0, start=1.0, track=2), AudioClip("m2.wav", 20.0, 0.0, 5.0, start=9.0, track=3)]
    p.overlays = [OverlayClip("o1.mp4", 5.0, 0.0, 3.0, start=2.0), OverlayClip("o2.mp4", 5.0, 0.0, 2.0, start=8.0),
                  OverlayClip("o3.mp4", 5.0, 0.0, 2.0, start=12.0)]
    p.effects = [{"id": "glitch", "intensity": 50, "start": 1.0, "end": 3.0}, {"id": "glitch", "intensity": 60, "start": 6.0, "end": 9.0},
                 {"id": "glitch", "intensity": 70, "start": 11.0, "end": 14.0}]
    return p


# clean
p = proj()
got = sel.clean(p, [("f", 2), ("v", 1), ("v", 1), ("x", 0), ("o", 9), ("a", -1), ("a", 0), ("v", 0)])
check(got == [("v", 0), ("v", 1), ("a", 0), ("f", 2)], got)
check(sel.clean(p, None) == [] and sel.counts(p) == (4, 2, 3, 3), "leer / Anzahl")
print("OK  Bereinigen")

# löschen: gemischt, mit getrenntem Ton
p = proj()
p.detach_audio(1)
n_a = len(p.audio_clips)
n = sel.delete(p, [("v", 1), ("v", 3), ("o", 0), ("o", 2), ("f", 1), ("a", 0)])
check(n == 6, n)
check([c.path for c in p.clips] == ["a.mp4", "c.mp4"], [c.path for c in p.clips])
check([o.path for o in p.overlays] == ["o2.mp4"] and len(p.effects) == 2 and [e["intensity"] for e in p.effects] == [50, 70], "Rest stimmt")
check(all(a.kind != "video" or p.clip_index(a.link) >= 0 for a in p.audio_clips), "kein Ton ohne Clip")
check(len(p.audio_clips) < n_a, "Audio gelöscht")
check(sel.delete(p, [("v", 99), ("a", 99)]) == 0, "ungültig ignoriert")
print("OK  Löschen")

# Löschen über einen getrennten Clip-Ton: der Clip-Ton wird mit dem Clip entfernt
p = proj()
p.detach_audio(0)
uid = p.clips[0].uid
sel.delete(p, [("v", 0)])
check(all(a.link != uid for a in p.audio_clips), "getrennter Ton des gelöschten Clips ist weg")
print("OK  getrennter Ton")

# duplizieren
p = proj()
new = sel.duplicate_items(p, [("v", 0), ("v", 2), ("o", 1), ("f", 0), ("f", 2)])
check([c.path for c in p.clips] == ["a.mp4", "a.mp4", "b.mp4", "c.mp4", "c.mp4", "d.mp4"], [c.path for c in p.clips])
check(("v", 1) in new and ("v", 4) in new and ("o", 2) in new and ("f", 1) in new and ("f", 4) in new, new)
check(len(new) == 5 and len(p.overlays) == 4 and len(p.effects) == 5, "Anzahl")
check(p.overlays[2].path == "o2.mp4" and abs(p.overlays[2].start - 10.0) < 1e-6, "Kopie des Bild-in-Bild direkt dahinter")
check(p.effects[1]["intensity"] == 50 and p.effects[4]["intensity"] == 70, "Kopien der Effekte an den neuen Nummern")
check(len({c.uid for c in p.clips}) == 6, "neue uid je Clip")
for k, i in new:
    check(0 <= i < {"v": len(p.clips), "o": len(p.overlays), "f": len(p.effects), "a": len(p.audio_clips)}[k], "Nummern gültig")
print("OK  Duplizieren")

# Audio duplizieren
p = proj()
new = sel.duplicate_items(p, [("a", 0), ("a", 1)])
check([a.path for a in p.audio_clips] == ["m1.wav", "m1.wav", "m2.wav", "m2.wav"] and new == [("a", 1), ("a", 3)], (new, [a.path for a in p.audio_clips]))
print("OK  Audio duplizieren")

# verschieben
p = proj()
p.audio_clips[0].kind = "video"                           # an Clip gebunden: nicht einzeln verschiebbar
p.audio_clips[0].link = p.clips[0].uid
items = [("v", 0), ("a", 0), ("a", 1), ("o", 0), ("f", 0)]
mv = sel.movable(p, items)
check(set(mv) == {("a", 1), ("o", 0), ("f", 0)}, set(mv))
d = sel.move(p, mv, 2.5)
check(d == 2.5 and abs(p.audio_clips[1].start - 11.5) < 1e-6 and abs(p.overlays[0].start - 4.5) < 1e-6 and p.fx_span(0) == (3.5, 5.5), (p.audio_clips[1].start, p.overlays[0].start, p.fx_span(0)))
d = sel.move(p, mv, -50.0)                                 # nicht vor 0: der Block mit dem kleinsten Anfang (Effekt bei 1,0) bestimmt
check(abs(d + 1.0) < 1e-6 and abs(p.audio_clips[1].start - 8.0) < 1e-6 and abs(p.overlays[0].start - 1.0) < 1e-6 and p.fx_span(0)[0] == 0.0, (d, p.fx_span(0)))
mv = sel.movable(p, [("f", 2), ("o", 2)])
d = sel.move(p, mv, 50.0)                                  # Effekt-Block endet bei 14, Projekt 16 s: höchstens 2 s
check(abs(d - 2.0) < 1e-6 and p.fx_span(2)[1] <= 16.0 + 1e-6, (d, p.fx_span(2)))
check(sel.move(p, {}, 3.0) == 0.0, "nichts zu verschieben")
print("OK  Verschieben")
print("ALLES OK")
