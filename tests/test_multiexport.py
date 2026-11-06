"""Mehrere Formate exportieren: Aufträge, Dateinamen und echte Exporte (Größe, Länge)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import exporter, multiexport as mx  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def raises(fn, *a):
    try:
        fn(*a)
    except mx.MultiExportError as e:
        return str(e)
    return None


# ---------------------------------------------------------------- Dateinamen
check(mx.safe_name('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j", mx.safe_name('a<b>c:d"e/f\\g|h?i*j'))
check(mx.safe_name("Mein Film.mp4") == "Mein Film" and mx.safe_name("  x. ") == "x", "Endung/Leerzeichen")
check(mx.safe_name("") == "Video" and mx.safe_name("CON") == "Video" and mx.safe_name("com1") == "Video" and mx.safe_name("...") == "Video", "leer/reserviert")
check(len(mx.safe_name("x" * 500)) == 120, "Länge begrenzt")
print("OK  Dateinamen")

src = tmp / "s.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
info = probe(str(src))
p = Project(format_id="youtube_16_9", export_id="youtube_1080p", layout="fill")
p.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height)]
out_dir = tmp / "out"
out_dir.mkdir()

# ---------------------------------------------------------------- Aufträge
check(raises(mx.plan, Project(), ["shorts"], out_dir, "x"), "ohne Clips")
check(raises(mx.plan, p, [], out_dir, "x"), "ohne Format")
check(raises(mx.plan, p, ["gibtsnicht"], out_dir, "x"), "unbekanntes Format")
check(raises(mx.plan, p, ["shorts"], tmp / "fehlt", "x"), "Ordner fehlt")
jobs = mx.plan(p, ["youtube_16_9", "shorts", "tiktok", "shorts", "insta_square"], out_dir, "Test: Film?")
check([j.format_id for j in jobs] == ["youtube_16_9", "shorts", "tiktok", "insta_square"], [j.format_id for j in jobs])
check(Path(jobs[0].out).name == "Test_ Film__youtube_16_9.mp4", Path(jobs[0].out).name)
check(len({j.out for j in jobs}) == 4, "Dateinamen verschieden")
check(jobs[0].project.layout == "fill" and all(j.project.layout == "" for j in jobs[1:]), "eigene Anpassung nur im eigenen Format")
check(jobs[1].project.export_id == "vertical_1080" and jobs[0].project.export_id == "youtube_1080p" and jobs[3].project.export_id == "square_1080", "Export-Presets")
check(p.format_id == "youtube_16_9" and p.layout == "fill" and p.export_id == "youtube_1080p", "Projekt unverändert")
check(jobs[1].project.clips[0] is not p.clips[0], "Kopie, nicht dasselbe Objekt")
# nichts überschreiben
Path(jobs[0].out).write_bytes(b"x")
j2 = mx.plan(p, ["youtube_16_9"], out_dir, "Test: Film?")
check(Path(j2[0].out).name == "Test_ Film__youtube_16_9_2.mp4", Path(j2[0].out).name)
Path(jobs[0].out).unlink()
print("OK  Aufträge")

# ---------------------------------------------------------------- echte Exporte
res = {}
for j in mx.plan(p, ["youtube_16_9", "shorts", "insta_square"], out_dir, "Film"):
    cmd, total, _ = exporter.build_command(j.project, j.out)
    exporter.run(cmd, total)
    i = probe(j.out)
    res[j.format_id] = (i.width, i.height, i.duration)
check(res["youtube_16_9"][:2] == (1920, 1080) and res["shorts"][:2] == (1080, 1920) and res["insta_square"][:2] == (1080, 1080), res)
check(all(abs(v[2] - 2.0) < 0.3 for v in res.values()), f"Längen: {res}")
check(len(list(out_dir.glob("Film_*.mp4"))) == 3, "drei Dateien")
print(f"OK  Export in 3 Formaten: {res}")
print("ALLES OK")
