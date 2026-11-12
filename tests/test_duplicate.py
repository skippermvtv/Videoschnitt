"""Duplizieren: Clip (mit getrenntem Ton, Übergang, Tempokurve), Bild-in-Bild, Audioblock, Effekt-Block."""
import os
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import duplicate  # noqa: E402
from app.core.project import AudioClip, Clip, OverlayClip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def raises(fn, *a):
    try:
        fn(*a)
    except duplicate.DuplicateError as e:
        return str(e)
    return None


def proj():
    p = Project()
    p.clips = [Clip("a.mp4", 10.0, 0.0, 4.0, has_audio=True, transition="fade", keyframes=[{"t": 0, "zoom": 100}, {"t": 1, "zoom": 150}]),
               Clip("b.mp4", 10.0, 0.0, 6.0, has_audio=True)]
    return p


# ---- Clip
p = proj()
a = p.clips[0]
i = duplicate.clip(p, 0)
c = p.clips[1]
check(i == 1 and len(p.clips) == 3 and c is not a, "Kopie direkt dahinter")
check(c.uid != a.uid and c.path == a.path and c.out_pt == a.out_pt, "neue uid, gleiche Werte")
check(a.transition == "" and c.transition == "fade", "Übergang wandert an die Kopie")
check(c.keyframes == a.keyframes and c.keyframes is not a.keyframes, "Keyframes kopiert, nicht geteilt")
check(p.clips[2].path == "b.mp4", "Rest verschoben")
print("OK  Clip")

# getrennter Ton
p = proj()
p.detach_audio(0)
p.detach_audio(1)
duplicate.clip(p, 0)
links = [x.link for x in p.audio_clips if x.kind == "video"]
check(len(p.audio_clips) == 3 and len(set(links)) == 3 and set(links) == {c.uid for c in p.clips}, f"Ton mitkopiert: {links}")
st = {x.link: x.start for x in p.audio_clips}
check(abs(st[p.clips[1].uid] - 4.0) < 1e-6 and abs(st[p.clips[2].uid] - 7.2) < 1e-6, f"Ton folgt der Kopie: {st}")
print("OK  Clip mit getrenntem Ton")

# Tempokurve wird nicht mitkopiert
p = proj()
p.clips[0].ramp_id, p.clips[0].ramp_pts, p.clips[0].ramp_speed = "r1", [[0, 1], [100, 2]], 1.5
duplicate.clip(p, 0)
check(p.clips[0].ramp_id == "r1" and p.clips[1].ramp_id == "" and p.clips[1].ramp_pts == [], "Tempokurve nur am Original")
print("OK  Tempokurve")

check(raises(duplicate.clip, Project(), 0), "ohne Clips")
check(raises(duplicate.clip, proj(), 5), "ungültiger Index")

# ---- Bild-in-Bild
p = proj()
p.overlays = [OverlayClip("o.mp4", 5.0, 0.0, 3.0, start=1.0, keys=[{"t": 0, "x": 10}, {"t": 1, "x": 90}])]
i = duplicate.overlay(p, 0)
o, n = p.overlays
check(i == 1 and abs(n.start - 4.0) < 1e-6 and n is not o and n.keys == o.keys and n.keys is not o.keys, "PiP direkt dahinter")
check(raises(duplicate.overlay, p, 9), "PiP ungültig")
print("OK  Bild-in-Bild")

# ---- Audio
p = proj()
p.audio_clips = [AudioClip("m.mp3", 20.0, 2.0, 8.0, start=1.0, track=2, volume=0.5)]
i = duplicate.audio(p, 0)
a0, a1 = p.audio_clips
check(i == 1 and abs(a1.start - 7.0) < 1e-6 and a1.track == 2 and a1.volume == 0.5 and a1.kind == "file", "Audio direkt dahinter")
p = proj()
p.detach_audio(0)
duplicate.audio(p, 0)
check(p.audio_clips[1].kind == "file" and p.audio_clips[1].link == "", "Kopie eines Clip-Tons ist frei")
p.sync_linked()
check(len(p.audio_clips) == 2, "freie Kopie bleibt nach Sync erhalten")
check(raises(duplicate.audio, proj(), 0), "Audio ungültig")
print("OK  Audio")

# ---- Effekt-Block
p = proj()                                   # Länge 10 s (ohne Übergang)
p.clips[0].transition = ""
p.effects = [{"id": "glitch", "intensity": 70, "start": 1.0, "end": 3.0, "extra": {"k": [1]}}]
i, fits = duplicate.effect(p, 0)
check(i == 1 and fits and p.fx_span(1) == (3.0, 5.0), p.fx_span(1))
check(p.effects[1]["id"] == "glitch" and p.effects[1]["intensity"] == 70 and p.effects[1]["extra"] is not p.effects[0]["extra"], "Werte kopiert")
# am Ende: gekürzt
p.effects = [{"id": "glitch", "intensity": 70, "start": 8.0, "end": 9.5}]
i, fits = duplicate.effect(p, 0)
s, e = p.fx_span(1)
check(fits and abs(s - 9.5) < 1e-6 and abs(e - 10.0) < 1e-6, f"gekürzt: {s}-{e}")
# bis zum Ende / ganzes Projekt: passt nicht dahinter
p.effects = [{"id": "glitch", "intensity": 70}]
i, fits = duplicate.effect(p, 0)
check(not fits and p.fx_span(1) == (0.0, 10.0), f"ganzes Projekt: {fits} {p.fx_span(1)}")
p.effects = [{"id": "glitch", "intensity": 70, "start": 7.0}]
i, fits = duplicate.effect(p, 0)
check(not fits and abs(p.fx_span(1)[1] - 10.0) < 1e-6 and p.fx_span(1)[0] >= 6.9, f"am Ende: {p.fx_span(1)}")
check(raises(duplicate.effect, proj(), 0), "Effekt ungültig")
print("OK  Effekt-Block")

# Speichern/Laden der Kopien
p = proj()
duplicate.clip(p, 0)
q = Project.from_json(p.to_json())
check(len(q.clips) == 3 and len({c.uid for c in q.clips}) == 3, "Speichern/Laden")
print("ALLES OK")
