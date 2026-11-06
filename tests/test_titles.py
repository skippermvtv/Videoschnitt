"""Titel-Vorlagen und Übergangs-Vorschaubilder (echtes FFmpeg)."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import exporter, presets, titles, transthumbs  # noqa: E402
from app.core.fontcheck import missing_chars  # noqa: E402
from app.core.project import TEXT_ANIMS, Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# ---------------------------------------------------------------- Vorlagen
tpls = titles.templates()
check(len(tpls) >= 10, f"zu wenige Vorlagen: {len(tpls)}")
ids = [t["id"] for t in tpls]
check(len(ids) == len(set(ids)), "doppelte IDs")
anims = {a for a, _ in TEXT_ANIMS}
fonts = {p.stem: str(p) for p in (paths.bundle_dir() / "fonts").glob("*.ttf")}
default_font = ""                      # Standardschrift – so legt das Programm Titel an
for t in tpls:
    L = titles.make_layer(t, 2.0, fonts, default_font)
    check(L.start == 2.0 and L.end > L.start + 0.4, (t["id"], L.start, L.end))
    check(L.position in ("top", "center", "bottom") and L.anim in anims, (t["id"], L.position, L.anim))
    check(t.get("info") and t["text"].strip(), f"{t['id']}: Beschreibung oder Text fehlt")
    miss = missing_chars(L.font, L.text)
    check(not miss, f"{t['id']}: Schrift hat nicht alle Zeichen: {miss}")
    if L.font:                                                       # eigene Schrift: wirklich vorhanden und alle Zeichen drin
        check(os.path.exists(L.font), f"{t['id']}: Schriftdatei fehlt")
check(next(t for t in tpls if t["id"] == "metal") and titles.make_layer(next(t for t in tpls if t["id"] == "metal"), 0, fonts, "x").font
      == fonts.get("FateMetal"), "Metal-Titel muss die mitgelieferte Schrift nehmen")
# kaputte Vorlage wird entschärft statt Fehler zu werfen
bad = titles.make_layer({"id": "x", "name": "x", "size_pct": "abc", "duration": -5, "position": "weit weg", "anim": "gibtsnicht"}, -3.0)
check(bad.start == 0.0 and bad.end >= 0.5 and bad.position == "center" and bad.anim == "none" and bad.size_pct == 7.0, bad)
print(f"OK  {len(tpls)} Vorlagen")

# Alle Vorlagen auf einmal in ein Projekt: Export läuft durch und die Texte sind zu sehen
src = tmp / "t.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x303840:s=640x360:r=25:d=14", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(src)], check=True)
info = probe(str(src))
p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
p.clips = [Clip(str(src), info.duration, has_audio=False, width=info.width, height=info.height)]
for k, t in enumerate(tpls):
    p.texts.append(titles.make_layer(t, k * 1.2, fonts, default_font))
out = tmp / "titles.mp4"
cmd, total, _ = exporter.build_command(p, str(out), draft=True, preview_height=270)
exporter.run(cmd, total)
check(out.exists() and out.stat().st_size > 5000, "Export fehlt")
png = tmp / "mid.png"
subprocess.run([ff, "-v", "error", "-y", "-ss", "1.9", "-i", str(out), "-frames:v", "1", str(png)], check=True)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
im = np.array(Image.open(png).convert("L")).astype(float)
check(im.std() > 8, f"Bild bei 1,9 s ist flach (std {im.std():.1f}) – Titel nicht zu sehen")
print("OK  Export mit allen Titeln")

# ---------------------------------------------------------------- Übergangsbilder
tr = presets.load("transitions")
hashes = {}
for x in tr:
    pth = transthumbs.make_thumb(x["id"], x.get("xfade", "fade"))
    im = Image.open(pth)
    check(im.size == (transthumbs.W, transthumbs.H), (x["id"], im.size))
    hashes[x["id"]] = hashlib.sha1(im.tobytes()).hexdigest()
check(len(set(hashes.values())) >= len(tr) - 6, f"zu viele gleiche Vorschaubilder: {len(set(hashes.values()))} von {len(tr)}")
check(transthumbs.make_thumb("fade", "fade") == transthumbs.make_thumb("fade", "fade"), "Zwischenspeicher")
try:
    transthumbs.make_thumb("kaputt", "gibtsnicht")
    check(False, "falscher Übergang muss einen Fehler melden")
except RuntimeError:
    pass
check(not transthumbs.thumb_path("kaputt").exists(), "kein Müll bei Fehlern")
print(f"OK  {len(tr)} Übergangsbilder ({len(set(hashes.values()))} verschieden)")
json.dumps(tpls)
print("ALLES OK")
