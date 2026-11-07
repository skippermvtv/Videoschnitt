"""Chroma-Key auf dem Hauptvideo: Greenscreen-Clip über einem Hintergrundbild / Hintergrundvideo / Schwarz."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import exporter, speedramp as sr  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def run(args):
    subprocess.run([ff, "-v", "error", "-y", *args], check=True)


# Vordergrund: grüner Schirm (0,255,0), links in der Mitte ein rotes Quadrat
fg = tmp / "fg.mp4"
run(["-f", "lavfi", "-i", "color=c=0x00ff00:s=320x180:r=25:d=3", "-vf", "drawbox=x=40:y=60:w=60:h=60:color=0xff0000:t=fill",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(fg)])
# Hintergrund: blaues Bild und ein gelbes Video
bg_png = tmp / "bg.png"
Image.new("RGB", (640, 360), (0, 0, 255)).save(bg_png)
bg_vid = tmp / "bg.mp4"
run(["-f", "lavfi", "-i", "color=c=0xffff00:s=160x90:r=25:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(bg_vid)])
info = probe(str(fg))


def render(name, bg="", color="#00ff00"):
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    c = Clip(str(fg), info.duration, has_audio=False, width=info.width, height=info.height)
    c.key_color, c.key_bg = color, bg
    p.clips = [c]
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True, preview_height=360)
    exporter.run(cmd, total)
    check(out.exists(), f"{name}: keine Ausgabe")
    oi = probe(str(out))
    check(abs(oi.duration - info.duration) < 0.2, f"{name}: Länge {oi.duration:.2f} statt {info.duration:.2f}")
    png = tmp / f"{name}.png"
    run(["-ss", "1.0", "-i", str(out), "-frames:v", "1", str(png)])
    return Image.open(png).convert("RGB")


def near(px, rgb, tol=60):
    return all(abs(a - b) <= tol for a, b in zip(px, rgb))


for name, bg, want in (("bild", str(bg_png), (0, 0, 255)), ("video", str(bg_vid), (255, 255, 0)), ("schwarz", "", (0, 0, 0))):
    im = render(name, bg)
    w, h = im.size
    check(near(im.getpixel((int(w * 0.8), int(h * 0.2))), want), f"{name}: Grün muss durch {want} ersetzt sein, ist {im.getpixel((int(w * 0.8), int(h * 0.2)))}")
    check(near(im.getpixel((int(w * 0.8), int(h * 0.8))), want), f"{name}: Hintergrund unten rechts {im.getpixel((int(w * 0.8), int(h * 0.8)))}")
    red = im.getpixel((int(w * 70 / 320), int(h * 90 / 180)))          # Mitte des roten Quadrats
    check(near(red, (255, 0, 0)), f"{name}: Motiv (rot) muss bleiben, ist {red}")
    print(f"OK  Hauptvideo mit Key über {name}")

# ohne Key bleibt alles grün (nichts verändert); ungültige Farbe = aus; fehlende Hintergrunddatei = schwarz
im = render("aus", str(bg_png), color="")
check(near(im.getpixel((int(im.size[0] * 0.8), int(im.size[1] * 0.2))), (0, 255, 0)), "ohne Key bleibt der grüne Schirm")
im = render("fehlt", str(tmp / "gibtsnicht.png"))
check(near(im.getpixel((int(im.size[0] * 0.8), int(im.size[1] * 0.2))), (0, 0, 0)), "fehlende Hintergrunddatei → schwarz")
print("OK  ohne Key / fehlender Hintergrund")

# Tempokurve zerschneidet den Clip: jedes Stück behält den Key
p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
c = Clip(str(fg), info.duration, has_audio=False, width=info.width, height=info.height)
c.key_color, c.key_bg = "#00ff00", str(bg_png)
p.clips = [c]
sr.apply(p, 0, [[0, 1], [50, 2], [100, 1]])
check(len(p.clips) > 2 and all(k.key_color == "#00ff00" and k.key_bg == str(bg_png) for k in p.clips), "Key wird beim Teilen vererbt")
out = tmp / "ramp.mp4"
cmd, total, _ = exporter.build_command(p, str(out), draft=True, preview_height=180)
exporter.run(cmd, total)
check(out.exists() and abs(probe(str(out)).duration - p.duration) < 0.35, "Export mit Tempokurve und Key")
print("OK  Key bleibt beim Teilen")

# Speichern/Laden; altes Projekt ohne Key-Felder lädt
import json  # noqa: E402
d = json.loads(p.to_json())
check(d["clips"][0]["key_color"] == "#00ff00" and Project.from_json(json.dumps(d)).clips[0].key_bg == str(bg_png), "Speichern/Laden")
for k in ("key_color", "key_similarity", "key_blend", "key_spill", "key_bg"):
    for cl in d["clips"]:
        cl.pop(k, None)
old = Project.from_json(json.dumps(d))
check(old.clips[0].key_color == "" and old.clips[0].key_bg == "", "altes Projekt ohne Key-Felder")
print("OK  Speichern/Laden, altes Projekt")
print("ALLES OK")
