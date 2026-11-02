"""Rückgängig/Wiederholen, Wiederfinden fehlender Dateien, Speichern/Laden (ohne Qt, ohne FFmpeg)."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.history import History
from app.core.project import AudioClip, Clip, Project

p = Project(); p.clips = [Clip("a.mp4", 5.0)]
h = History(p.to_json())
t = 0.0
def step(dt=0.3):
    global t; t += dt; h.observe(p.to_json(), t)

# Reglerserie = ein Schritt
for v in (1.0, 1.1, 1.2, 1.3):
    p.clips[0].volume = v; step(0.1)
for _ in range(4): step()
assert len(h._undo) == 1 and h.can_undo()
# zweite Änderung
p.clips.append(Clip("b.mp4", 3.0)); step()
for _ in range(4): step()
assert len(h._undo) == 2
# Undo bringt Zustand 1 zurück, Redo wieder vor
s = h.undo(p.to_json()); q = Project.from_json(s); assert len(q.clips) == 1 and q.clips[0].volume == 1.3
s = h.undo(q.to_json()); q = Project.from_json(s); assert q.clips[0].volume == 1.0
assert h.undo(q.to_json()) is None
s = h.redo(); assert Project.from_json(s).clips[0].volume == 1.3
s = h.redo(); assert len(Project.from_json(s).clips) == 2
assert h.redo() is None
# Änderung vor dem Settle: Undo erfasst sie trotzdem
p = Project.from_json(s); p.clips[0].speed = 2.0; h.observe(p.to_json(), t + 0.1)
s = h.undo(p.to_json()); assert Project.from_json(s).clips[0].speed == 1.0
# neue Änderung nach Undo löscht Redo
p = Project.from_json(s); p.clips[0].mute = True; t += 1; h.observe(p.to_json(), t); t += 1; h.observe(p.to_json(), t)
assert not h.can_redo()
print("OK  Rückgängig/Wiederholen")

# Fehlende Dateien finden
d = Path(tempfile.mkdtemp()); (d / "sub").mkdir(); (d / "sub" / "A.MP4").write_bytes(b"x"); (d / "m.wav").write_bytes(b"x")
pr = Project(); pr.clips = [Clip("C:/alt/a.mp4", 3.0), Clip("C:/alt/b.mp4", 3.0)]
pr.audio_clips = [AudioClip("C:/alt/m.wav", 2.0)]
assert len(pr.missing_paths()) == 3
n, still = pr.relink(str(d))
assert n == 2 and still == ["C:/alt/b.mp4"], (n, still)
assert pr.clips[0].path.endswith("A.MP4") and pr.audio_clips[0].path.endswith("m.wav")
print("OK  Dateien wiederfinden")
# alte Projektdatei mit unbekannten Feldern lädt
import json
dd = json.loads(Project().to_json()); dd["texts"] = [{"text": "x", "neu": 1}]; dd["clips"] = [{"path": "a", "duration": 2, "zukunft": 5}]
assert Project.from_json(json.dumps(dd)).texts[0].text == "x"
print("ALLES OK")
