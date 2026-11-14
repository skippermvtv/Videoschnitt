"""1.5.4 Beschleunigungen: schnelles to_json (gleicher Inhalt wie asdict), kompakt vs. eingerückt, probe_many (parallel)."""
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
tmp.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.project import (AudioClip, Clip, OverlayClip, Project, SubtitleCue, TextLayer, probe, probe_many)  # noqa: E402
from app.paths import find_binary  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# --- to_json
p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
for i in range(12):
    p.clips.append(Clip(str(tmp / f"a{i}.mp4"), 10.0, has_audio=True, width=1920, height=1080, in_pt=i * 0.5, out_pt=i * 0.5 + 4,
                        keyframes=[{"t": 0.0, "zoom": 1.0}, {"t": 1.0, "zoom": 1.5}] if i % 2 else []))
p.overlays = [OverlayClip(str(tmp / "o.mp4"), 5.0, cell=[0, 0, 50, 50])]
p.audio_clips = [AudioClip(str(tmp / "m.wav"), 20.0)]
p.subtitles = [SubtitleCue(0.0, 1.0, "Größe: äöü ß „Test“")]
p.texts = [TextLayer("Hallo")] if hasattr(p, "texts") else []
alt = json.dumps(asdict(p), ensure_ascii=False, indent=2)
check(p.to_json(indent=2) == alt, "eingerückter Text weicht von asdict ab")
check(json.loads(p.to_json()) == json.loads(alt), "kompakter Text hat anderen Inhalt")
check(len(p.to_json()) < len(alt) * 0.9, (len(p.to_json()), len(alt)))
q = Project.from_json(p.to_json())
check(q.to_json() == p.to_json(), "Hin und zurück ergibt anderen Text")
f = tmp / "speed154.cforge"
p.save(str(f))
text = f.read_text(encoding="utf-8")
check(text == alt and "\n  " in text, "gespeicherte Datei ist nicht eingerückt")
check(Project.load(str(f)).to_json() == q.to_json(), "Laden gibt anderen Stand")
print("OK  to_json schnell und gleichwertig")

# --- clip_starts (ein Durchlauf statt je Clip eine Summe)
big = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
for i in range(400):
    big.clips.append(Clip(str(tmp / "x.mp4"), 30.0, in_pt=(i * 0.37) % 5, out_pt=(i * 0.37) % 5 + 8 + (i % 3) * 0.13, speed=1 + (i % 4) * 0.25,
                          transition="fade" if i % 5 == 0 else "", transition_dur=0.5))
a, b = big.clip_starts(), [big.clip_start(i) for i in range(400)]
check(len(a) == 400 and max(abs(x - y) for x, y in zip(a, b)) < 1e-9, "clip_starts weicht ab")
check(abs(a[-1] + big.clips[-1].length - big.duration) < 1e-6, "letzter Clip endet nicht bei duration")
check(Project().clip_starts() == [], "leeres Projekt")
print("OK  clip_starts")

# --- probe_many
ff = find_binary("ffmpeg")
good = []
for i in range(5):
    out = tmp / f"speed154_{i}.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s=160x90:r=10:d={1 + i}", "-pix_fmt", "yuv420p", str(out)], check=True)
    good.append(str(out))
bad = tmp / "speed154_kaputt.mp4"
bad.write_bytes(b"das ist kein video")
missing = str(tmp / "speed154_fehlt.mp4")
files = good + [str(bad), missing, good[0]]            # inkl. Doppelgänger
res = probe_many(files)
check(list(res) == good + [str(bad), missing], list(res))      # Reihenfolge, Duplikat nur einmal
for i, g in enumerate(good):
    single = probe(g)
    check(res[g] == single and abs(res[g].duration - (1 + i)) < 0.3, (g, res[g], single))
check(isinstance(res[str(bad)], Exception) and isinstance(res[missing], Exception), "Fehlerfälle")
check(str(res[str(bad)]) != "" and str(res[missing]) != "", "Fehlertexte leer")
check(probe_many([]) == {} and isinstance(probe_many([missing])[missing], Exception), "leer/einzeln")
print("OK  probe_many")
print("ALLES OK")
