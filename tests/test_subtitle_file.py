"""Untertitel-Datei beim Export: SRT passt zur Videolänge, Einbrennen an/aus (Pixelvergleich), Speichern/Laden."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import exporter, subtitles as subs  # noqa: E402
from app.core.project import Clip, Project, SubtitleCue, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


src = tmp / "black.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:size=640x360:rate=25:duration=3", "-f", "lavfi", "-i", "sine=duration=3",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
info = probe(str(src))


def make():
    p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
    p.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height),
               Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height, transition="fade", transition_dur=0.5)]
    p.clips = p.clips[::-1]            # Übergang am ersten Clip: Gesamtlänge ≈ 5,5 s
    p.subtitles = [SubtitleCue(0.5, 1.5, "Hallo Welt"), SubtitleCue(4.0, 9.0, "Zu lang"), SubtitleCue(7.0, 8.0, "Danach"),
                   SubtitleCue(2.0, 2.5, "  "), SubtitleCue(2.6, 3.0, "Zeile eins\n\nZeile zwei")]
    return p


p = make()
total = p.duration
check(abs(total - 5.5) < 0.1, f"Projektlänge {total}")

# Pfad und Einträge
check(Path(subs.srt_path_for("/a/b/Mein Film.mp4")) == Path("/a/b/Mein Film.srt"), subs.srt_path_for("/a/b/Mein Film.mp4"))   # Windows: Backslashes
cues = subs.export_cues(p)
check([c.text for c in cues] == ["Hallo Welt", "Zeile eins\nZeile zwei", "Zu lang"], [c.text for c in cues])
check(abs(cues[-1].end - total) < 1e-6 and all(c.end <= total + 1e-6 for c in cues), "Einträge auf die Videolänge begrenzt")
print("OK  Einträge")

# echte Datei
out = tmp / "Mein Film.mp4"
cmd, tot, _ = exporter.build_command(p, str(out))
exporter.run(cmd, tot)
path = subs.write_export_srt(p, str(out))
check(path == str(tmp / "Mein Film.srt") and Path(path).is_file(), path)
raw = Path(path).read_bytes()
check(not raw.startswith(b"\xef\xbb\xbf"), "UTF-8 ohne BOM (YouTube nimmt beides, ohne ist sauberer)")
back = subs.read_srt(path)
check([c.text for c in back] == [c.text for c in cues], "SRT lässt sich wieder einlesen")
vlen = probe(str(out)).duration
check(max(c.end for c in back) <= vlen + 0.1, f"SRT endet {max(c.end for c in back)} nach dem Video {vlen}")
check(Path(path).read_text(encoding="utf-8").count("-->") == 3, "drei Blöcke")
p2 = make()
p2.subtitles = []
check(subs.write_export_srt(p2, str(tmp / "leer.mp4")) is None and not (tmp / "leer.srt").exists(), "ohne Untertitel keine Datei")
print("OK  SRT-Datei passt zum Video")


def bright_pixels(project, name):
    o = tmp / f"{name}.mp4"
    cmd, tot, _ = exporter.build_command(project, str(o))
    exporter.run(cmd, tot)
    i = probe(str(o))
    raw = subprocess.run([ff, "-v", "error", "-ss", "1.0", "-i", str(o), "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return int((np.frombuffer(raw, np.uint8).reshape(i.height, i.width) > 100).sum())


on = make()
off = make()
off.sub_burn = False
n_on, n_off = bright_pixels(on, "burn_on"), bright_pixels(off, "burn_off")
check(n_on > 300, f"eingebrannt: zu wenig helle Pixel ({n_on})")
check(n_off < 20, f"nicht eingebrannt: Bild muss schwarz bleiben ({n_off})")
print(f"OK  Einbrennen an ({n_on} helle Pixel) / aus ({n_off})")

# Speichern/Laden, altes Projekt
q = Project.from_json(off.to_json())
check(q.sub_burn is False and q.sub_srt is False, "Laden")
off.sub_srt = True
check(Project.from_json(off.to_json()).sub_srt is True, "sub_srt gespeichert")
d = json.loads(off.to_json())
d.pop("sub_burn"), d.pop("sub_srt")
old = Project.from_json(json.dumps(d))
check(old.sub_burn is True and old.sub_srt is False, "altes Projekt: einbrennen wie bisher, keine Datei")
print("OK  Speichern/Laden")
print("ALLES OK")
