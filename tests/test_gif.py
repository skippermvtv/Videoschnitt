"""GIF-Export: echte Dateien – Größe, Bildzahl, Schleife, Farben, begrenzte Länge, Hochformat."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image  # noqa: E402

from app import paths  # noqa: E402
from app.core import exporter, gif  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


src = tmp / "s.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=3", "-f", "lavfi", "-i", "sine=duration=3",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
info = probe(str(src))


def make(fmt):
    p = Project(format_id=fmt, export_id="youtube_1080p", layout="fill")
    p.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height)]
    return p


def build(p, name, width, fps, secs=None):
    w, h = gif.size_for(p, width)
    mid = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(mid), draft=True, preview_height=h, max_seconds=secs)
    exporter.run(cmd, total)
    out = tmp / f"{name}.gif"
    exporter.run(gif.gif_command(str(mid), str(out), width, fps), total)
    return out, w, h


# Größe aus dem Seitenverhältnis
check(gif.size_for(make("youtube_16_9"), 480) == (480, 270), gif.size_for(make("youtube_16_9"), 480))
check(gif.size_for(make("shorts"), 320) == (320, 568), gif.size_for(make("shorts"), 320))
check(gif.size_for(make("insta_square"), 321) == (320, 320), "gerade Breite")
secs, cut = gif.length_for(make("youtube_16_9"))
check(abs(secs - 3.0) < 0.2 and not cut, (secs, cut))
check("MB" in gif.describe(make("youtube_16_9"), 480, 12), gif.describe(make("youtube_16_9"), 480, 12))
long = make("youtube_16_9")
long.clips[0].out_pt = info.duration
long.clips = long.clips * 12                          # 36 s
check(gif.length_for(long) == (30.0, True) and "ersten 30" in gif.describe(long, 480, 12), "lange Projekte gekürzt")
check(gif.default_name("a/b.mp4").endswith("b.gif") and gif.default_name("x.GIF") == "x.GIF", "Endung")
print("OK  Größen und Längen")

for fmt, width, fps in (("youtube_16_9", 480, 10), ("shorts", 320, 12)):
    out, w, h = build(make(fmt), f"g_{fmt}", width, fps)
    im = Image.open(out)
    check(im.format == "GIF" and im.size == (w, h), f"{fmt}: Größe {im.size} statt {(w, h)}")
    n = im.n_frames
    check(abs(n - fps * 3) <= 3, f"{fmt}: {n} Bilder, erwartet etwa {fps * 3}")
    check(im.info.get("loop", -1) == 0, f"{fmt}: Schleife {im.info.get('loop')}")
    im.seek(n // 2)
    rgb = im.convert("RGB")
    colors = rgb.getcolors(maxcolors=100000)
    check(colors is not None and len(colors) > 8, f"{fmt}: Bild hat zu wenige Farben")
    check(out.stat().st_size > 5_000, "Datei nicht leer")
    print(f"OK  {fmt}: {w}x{h}, {n} Bilder, {out.stat().st_size // 1024} KB")

# gekürzt auf 1 s
out, w, h = build(make("youtube_16_9"), "g_short", 320, 10, secs=1.0)
n = Image.open(out).n_frames
check(8 <= n <= 12, f"1 s ergibt {n} Bilder")
print("OK  Länge begrenzt")
print("ALLES OK")
