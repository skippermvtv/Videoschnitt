"""Stapel-Export: mehrere Projektdateien lesen, Aufträge planen, Probleme melden, echte Exporte."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import batch, exporter  # noqa: E402
from app.core.multiexport import MultiExportError  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def raises(fn, *a):
    try:
        fn(*a)
    except MultiExportError as e:
        return str(e)
    return None


src = tmp / "batch_src.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
info = probe(str(src))


def make(name, fmt="youtube_16_9", clips=1, media=None, folder="proj"):
    d = tmp / "batch" / folder
    d.mkdir(parents=True, exist_ok=True)
    p = Project(format_id=fmt, export_id="fast_draft", layout="fill")
    p.clips = [Clip(str(media or src), info.duration, has_audio=True, width=info.width, height=info.height) for _ in range(clips)]
    f = d / f"{name}.cforge"
    p.save(str(f))
    return str(f)


f_a = make("Folge 1")
f_b = make("Folge 2", fmt="shorts")
f_empty = make("Leer", clips=0)
f_gone = make("Fehlt", media=tmp / "gibt_es_nicht.mp4")
f_bad = tmp / "batch" / "proj" / "Kaputt.cforge"
f_bad.write_text("{ das ist kein json", encoding="utf-8")
f_a2 = make("Folge 1", folder="anderer_ordner")                    # gleicher Name in anderem Ordner
(tmp / "batch" / "proj" / "notiz.txt").write_text("x", encoding="utf-8")

# ---------------------------------------------------------------- Lesen
found = batch.find_projects(str(tmp / "batch" / "proj"))
check([Path(x).name for x in found] == sorted(["Folge 1.cforge", "Folge 2.cforge", "Fehlt.cforge", "Kaputt.cforge", "Leer.cforge"], key=str.lower), found)
check(batch.find_projects(str(tmp / "nix")) == [], "Ordner fehlt")
items = batch.load_items([f_a, f_b, f_empty, f_gone, str(f_bad), f_a2, f_a])          # f_a doppelt
check(len(items) == 6, len(items))
by = {Path(i.file).name + "|" + Path(i.file).parent.name: i for i in items}
check(not by["Folge 1.cforge|proj"].problem and not by["Folge 2.cforge|proj"].problem, "gute Projekte")
check("keine Clips" in by["Leer.cforge|proj"].problem, by["Leer.cforge|proj"].problem)
check("fehlt" in by["Fehlt.cforge|proj"].problem and "gibt_es_nicht.mp4" in by["Fehlt.cforge|proj"].problem, by["Fehlt.cforge|proj"].problem)
check("nicht lesbar" in by["Kaputt.cforge|proj"].problem, by["Kaputt.cforge|proj"].problem)
print("OK  Lesen")

# ---------------------------------------------------------------- Planen
out_dir = tmp / "out_batch"
out_dir.mkdir(exist_ok=True)
check(raises(batch.plan, items, [], out_dir), "ohne Format")
check(raises(batch.plan, items, ["gibtsnicht"], out_dir), "unbekanntes Format")
check(raises(batch.plan, items, ["shorts"], tmp / "fehlt"), "Ordner fehlt")
check("Kein Projekt" in (raises(batch.plan, [by["Leer.cforge|proj"], by["Kaputt.cforge|proj"]], ["shorts"], out_dir) or ""), "nichts exportierbar")
pl = batch.plan(items, ["youtube_16_9", "shorts"], out_dir)
check(len(pl.jobs) == 6, [j.out for j in pl.jobs])                      # 3 gute Projekte × 2 Formate
check(len({j.out for j in pl.jobs}) == 6, "alle Dateinamen verschieden (auch 2× „Folge 1“)")
check(len(pl.notes) == 3 and any("Leer.cforge" in n for n in pl.notes) and any("Kaputt.cforge" in n for n in pl.notes)
      and any("Fehlt.cforge" in n for n in pl.notes), pl.notes)
check(all(j.label.startswith(("Folge 1:", "Folge 2:")) for j in pl.jobs), [j.label for j in pl.jobs])
check(pl.jobs[0].project is not items[0].project, "Kopie")
print("OK  Planen")

# „Format wie im Projekt“
own = batch.plan(items, [batch.OWN_FORMAT], out_dir)
check([j.format_id for j in own.jobs] == ["youtube_16_9", "shorts", "youtube_16_9"], [j.format_id for j in own.jobs])
check(all(j.project.layout == "fill" for j in own.jobs), "eigene Bildanpassung bleibt")
mix = batch.plan([by["Folge 1.cforge|proj"]], [batch.OWN_FORMAT, "youtube_16_9", "shorts"], out_dir)
check([j.format_id for j in mix.jobs] == ["youtube_16_9", "shorts"], [j.format_id for j in mix.jobs])    # eigenes Format nicht doppelt
mix2 = batch.plan([by["Folge 2.cforge|proj"]], [batch.OWN_FORMAT, "youtube_16_9"], out_dir)
check([j.format_id for j in mix2.jobs] == ["shorts", "youtube_16_9"], [j.format_id for j in mix2.jobs])
# nichts überschreiben
Path(pl.jobs[0].out).write_bytes(b"x")
pl2 = batch.plan(items, ["youtube_16_9"], out_dir)
check(Path(pl2.jobs[0].out).name != Path(pl.jobs[0].out).name, "vorhandene Datei bleibt")
Path(pl.jobs[0].out).unlink()
# Projekte unverändert
check(items[0].project.format_id == "youtube_16_9" and items[1].project.format_id == "shorts", "Quellprojekte unverändert")
print("OK  eigenes Format, Namen, nichts überschreiben")

# ---------------------------------------------------------------- Echt exportieren
res = {}
for j in batch.plan([by["Folge 1.cforge|proj"], by["Folge 2.cforge|proj"]], ["shorts", "insta_square"], out_dir).jobs:
    cmd, total, _ = exporter.build_command(j.project, j.out)
    exporter.run(cmd, total)
    i = probe(j.out)
    res[Path(j.out).name] = (i.width, i.height, round(i.duration, 1))
check(len(res) == 4 and all(v[:2] in ((1080, 1920), (1080, 1080)) and abs(v[2] - 2.0) < 0.3 for v in res.values()), res)
print(f"OK  echter Export: {res}")
print("ALLES OK")
