"""Projekt sammeln: Ordner und ZIP, Namenskonflikte, fehlende Dateien, relative Pfade beim Öffnen, Abbruch."""
import os
import sys
import tempfile
import zipfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import collect  # noqa: E402
from app.core.project import AudioClip, Clip, OverlayClip, Project, TextLayer  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


src = tmp / "quellen"
(src / "a").mkdir(parents=True, exist_ok=True)
(src / "b").mkdir(parents=True, exist_ok=True)


def mk(rel, data):
    f = src / rel
    f.write_bytes(data)
    return str(f)


v1 = mk("a/clip.mp4", b"V1" * 1000)
v2 = mk("b/clip.mp4", b"V2" * 500)           # gleicher Name, anderer Ordner
lut = mk("look.cube", b"LUT")
png = mk("logo.png", b"PNG")
mp3 = mk("musik.mp3", b"M" * 3000)
font = mk("schrift.ttf", b"FONT")
gone = str(src / "weg.mp4")

p = Project()
p.clips = [Clip(v1, 10.0, 0.0, 5.0), Clip(v2, 10.0, 0.0, 5.0), Clip(v1, 10.0, 5.0, 10.0), Clip(gone, 10.0, 0.0, 5.0)]
p.clips[0].grade = {"lut": lut}
p.clips[1].key_bg = png
p.audio_clips = [AudioClip(mp3, 20.0, 0.0, 6.0, start=1.0)]
p.overlays = [OverlayClip(png, 5.0, 0.0, 2.0, start=1.0, is_image=True)]
p.watermark = png
p.texts = [TextLayer(text="Hi", font=font)]
p.sub_style.font = font
before = p.to_json()

files = collect.used_files(p)
check(len(files) == len(set(files)) and set(files) == {v1, v2, lut, png, mp3, font, gone}, files)
s = collect.summary(p)
check(s["missing"] == [gone] and s["bytes"] == 2000 + 1000 + 3 + 3 + 3000 + 4, s)
names = collect._plan(files)
check(names[v1] != names[v2] and names[v1].startswith("Medien/") and names[v2].lower().startswith("medien/clip"), names)
print("OK  Dateien finden, Namenskonflikt")

# Ordner
out = tmp / "ziel"
seen = []
r = collect.collect(p, str(out), name="Mein Film", on_progress=lambda f, n: seen.append(f))
check(r["files"] == 6 and r["missing"] == [gone] and Path(r["project"]).name == "Mein Film.cforge", r)
check(p.to_json() == before, "Projekt bleibt unverändert")
check(seen and seen[-1] > 0.99, seen[-3:])
check(len(list((out / "Medien").iterdir())) == 6, list((out / "Medien").iterdir()))
loaded = Project.load(r["project"])
check(all(os.path.isabs(c.path) for c in loaded.clips), [c.path for c in loaded.clips])
check(loaded.clips[0].path == loaded.clips[2].path and os.path.isfile(loaded.clips[0].path), "gleiche Datei nur einmal kopiert")
check(loaded.clips[0].path != loaded.clips[1].path and Path(loaded.clips[1].path).read_bytes() == b"V2" * 500, "zweite Datei gleichen Namens")
check(loaded.clips[3].path == gone, "fehlende Datei bleibt, wie sie war")
check(Path(loaded.clips[0].grade["lut"]).read_bytes() == b"LUT" and Path(loaded.clips[1].key_bg).read_bytes() == b"PNG", "LUT und Hintergrund")
check(Path(loaded.watermark).is_file() and Path(loaded.texts[0].font).is_file() and Path(loaded.sub_style.font).is_file(), (loaded.watermark, loaded.texts, loaded.sub_style.font))
check(Path(loaded.audio_clips[0].path).read_bytes() == b"M" * 3000 and Path(loaded.overlays[0].path).is_file(), "Ton und Bild-in-Bild")
check(str(out.resolve()) in str(Path(loaded.clips[0].path).resolve()), "Pfade zeigen in den Zielordner")
print("OK  Ordner sammeln und wieder öffnen")

# Ordner umziehen: Pfade folgen
moved = tmp / "umgezogen"
os.rename(out, moved)
l2 = Project.load(str(moved / "Mein Film.cforge"))
check(os.path.isfile(l2.clips[0].path) and str(moved.resolve()) in str(Path(l2.clips[0].path).resolve()), l2.clips[0].path)
print("OK  Ordner umgezogen")

# ZIP
z = tmp / "paket" / "film.zip"
r = collect.collect(p, str(z), as_zip=True, name="Film")
check(z.is_file() and not Path(str(z) + ".teil").exists(), "ZIP vorhanden, keine Reste")
with zipfile.ZipFile(z) as zf:
    nm = zf.namelist()
    check("Film.cforge" in nm and len([n for n in nm if n.startswith("Medien/")]) == 6, nm)
    check(zf.read("Medien/musik.mp3") == b"M" * 3000, "Inhalt")
    check(zf.testzip() is None, "ZIP in Ordnung")
    pj = Project.from_json(zf.read("Film.cforge").decode("utf-8"))
    check(pj.clips[0].path.startswith("Medien/") and pj.clips[3].path == gone, (pj.clips[0].path, pj.clips[3].path))
print("OK  ZIP")

# Abbruch
z2 = tmp / "abbruch.zip"
try:
    collect.collect(p, str(z2), as_zip=True, should_cancel=lambda: True)
except collect.Cancelled:
    pass
else:
    check(False, "Abbruch muss Cancelled auslösen")
check(not z2.exists() and not Path(str(z2) + ".teil").exists(), "nach Abbruch bleibt nichts liegen")
try:
    collect.collect(p, str(tmp / "abbruch_ordner"), should_cancel=lambda: True)
except collect.Cancelled:
    pass
check(not (tmp / "abbruch_ordner").exists(), "Ordner nach Abbruch entfernt")
print("OK  Abbruch")

# absolute Pfade bleiben, leeres Projekt
q = Project.from_json(before)
check(collect.absolutize(q, tmp) == 0 and q.to_json() == before, "absolute Pfade bleiben")
e = collect.collect(Project(), str(tmp / "leer"), name="x")
check(e["files"] == 0 and (tmp / "leer" / "x.cforge").is_file(), e)
print("OK  Sonderfälle")
print("ALLES OK")
