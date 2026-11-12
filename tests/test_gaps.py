"""Ripple-Löschen und "Alle Lücken schließen" (Projektdaten)."""
import os
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import gaps  # noqa: E402
from app.core.project import AudioClip, Clip, OverlayClip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def proj():
    p = Project()
    p.clips = [Clip(f"{n}.mp4", 10.0, 0.0, 4.0, has_audio=True) for n in "abcd"]           # 16 s, Clips bei 0/4/8/12
    p.audio_clips = [AudioClip("m1.wav", 20.0, 0.0, 3.0, start=1.0, track=2), AudioClip("m2.wav", 20.0, 0.0, 3.0, start=9.0, track=3)]
    p.overlays = [OverlayClip("o1.mp4", 5.0, 0.0, 2.0, start=1.0), OverlayClip("o2.mp4", 5.0, 0.0, 2.0, start=5.0),
                  OverlayClip("o3.mp4", 5.0, 0.0, 2.0, start=9.0), OverlayClip("o4.mp4", 5.0, 0.0, 3.0, start=3.0)]
    p.effects = [{"id": "glitch", "intensity": 50, "start": 1.0, "end": 3.0}, {"id": "glitch", "intensity": 60, "start": 5.0, "end": 7.0},
                 {"id": "glitch", "intensity": 70, "start": 10.0, "end": 14.0}, {"id": "bw", "intensity": 100}]
    return p


# Ripple: Clip 2 (4–8 s) löschen
p = proj()
r = gaps.ripple_delete(p, [1])
check(r["clips"] == 1 and abs(r["seconds"] - 4.0) < 1e-6 and abs(p.duration - 12.0) < 1e-6, r)
names = [o.path for o in p.overlays]
check(names == ["o1.mp4", "o3.mp4", "o4.mp4"], ("o2 lag komplett im Stück und fällt weg", names))
check(r["removed"] == 2, r)                           # o2 und der Effekt 5–7 s
st = {o.path: o.start for o in p.overlays}
check(st["o1.mp4"] == 1.0 and st["o3.mp4"] == 5.0, st)
check(abs(st["o4.mp4"] - 3.0) < 1e-6, ("o4 (3–6 s) ragt hinein: Anfang bleibt", st))
check([a.start for a in p.audio_clips] == [1.0, 5.0], [a.start for a in p.audio_clips])
fx = [(e["id"], p.fx_span(i)) for i, e in enumerate(p.effects)]
check(fx[0] == ("glitch", (1.0, 3.0)) and fx[1] == ("glitch", (6.0, 10.0)) and fx[2][0] == "bw", fx)
check(p.effects[2].get("start") is None, "Projektweiter Effekt bleibt projektweit")
print("OK  Ripple-Löschen")

# Ripple: erster und letzter Clip zusammen
p = proj()
r = gaps.ripple_delete(p, [0, 3, 3, 9, -1])
check(r["clips"] == 2 and abs(p.duration - 8.0) < 1e-6 and len(p.clips) == 2, r)
check(all(0 <= o.start for o in p.overlays), "keine negativen Zeiten")
check([o.path for o in p.overlays] == ["o2.mp4", "o4.mp4"] or len(p.overlays) >= 1, [o.path for o in p.overlays])
print("OK  Ripple mehrere Clips")

# Ripple mit getrenntem Ton: Ton folgt dem Clip und bleibt unberührt in _shift_after
p = proj()
p.detach_audio(2)
n_before = len([a for a in p.audio_clips if a.kind == "video"])
gaps.ripple_delete(p, [1])
check(len([a for a in p.audio_clips if a.kind == "video"]) == n_before, "gebundener Ton bleibt erhalten")
check(all(p.clip_index(a.link) >= 0 for a in p.audio_clips if a.kind == "video"), "Verknüpfung bleibt gültig")
print("OK  Ripple mit getrenntem Ton")

# Ripple ohne Wirkung
p = proj()
r = gaps.ripple_delete(p, [])
check(r == {"clips": 0, "removed": 0, "seconds": 0.0}, r)
print("OK  Ripple leer")

# Effekt mit offenem Ende (start > 0, end None) rückt nach
p = proj()
p.effects = [{"id": "glitch", "intensity": 50, "start": 9.0, "end": None}]
gaps.ripple_delete(p, [0])
check(abs(p.fx_span(0)[0] - 5.0) < 1e-6 and abs(p.fx_span(0)[1] - p.duration) < 1e-6, p.fx_span(0))
print("OK  Effekt mit offenem Ende")

# Lücken zählen und schließen
p = Project()
p.clips = [Clip("a.mp4", 30.0, 0.0, 30.0, has_audio=True)]
p.overlays = [OverlayClip("o1.mp4", 5.0, 0.0, 2.0, start=1.0), OverlayClip("o2.mp4", 5.0, 0.0, 2.0, start=5.0),
              OverlayClip("o3.mp4", 5.0, 0.0, 2.0, start=6.0), OverlayClip("o4.mp4", 5.0, 0.0, 2.0, start=20.0)]
p.audio_clips = [AudioClip("m1.wav", 20.0, 0.0, 3.0, start=2.0, track=2), AudioClip("m2.wav", 20.0, 0.0, 3.0, start=10.0, track=2),
                 AudioClip("m3.wav", 20.0, 0.0, 3.0, start=25.0, track=3)]
p.effects = [{"id": "glitch", "intensity": 50, "start": 2.0, "end": 4.0}, {"id": "glitch", "intensity": 60, "start": 8.0, "end": 10.0}]
check(gaps.count_gaps(p) == 4, gaps.count_gaps(p))     # Bild-in-Bild: 3→5 und 8→20; Musik 5→10; Effekte 4→8
r = gaps.close_all(p)
st = [o.start for o in p.overlays]
check(st == [1.0, 3.0, 4.0, 6.0], ("o3 überlappt o2 weiter, o4 rückt an", st))
check(p.audio_clips[1].start == 5.0 and p.audio_clips[2].start == 25.0, [a.start for a in p.audio_clips])
check(p.fx_span(1) == (4.0, 6.0), p.fx_span(1))
check(gaps.count_gaps(p) == 0 and r["gaps"] == 4, (r, gaps.count_gaps(p)))
check(gaps.close_all(p)["gaps"] == 0, "zweiter Durchlauf ändert nichts")
print("OK  Lücken schließen")
print("OK  test_gaps")
