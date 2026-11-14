"""Proxy-Dateien: Entscheidung, Erzeugung mit echtem FFmpeg, gleiche Länge/Ton, Ersetzen für die Vorschau, Abbruch."""
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
from app.core import exporter, proxy, stillframe  # noqa: E402
from app.core.project import Clip, OverlayClip, Project  # noqa: E402

ff, fp = paths.find_binary("ffmpeg"), paths.find_binary("ffprobe")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def sh(*args):
    subprocess.run([ff, "-v", "error", "-y", *args], check=True)


def streams(f):
    r = subprocess.run([fp, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(f)], capture_output=True, text=True)
    return json.loads(r.stdout)


# Entscheidung
check(not proxy.is_heavy({"width": 1920, "height": 1080, "codec": "h264", "bitrate": 8_000_000}), "Full HD H.264 braucht keinen Proxy")
check(proxy.is_heavy({"width": 3840, "height": 2160, "codec": "h264", "bitrate": 8_000_000}), "4K")
check(proxy.is_heavy({"width": 1080, "height": 1920, "codec": "hevc", "bitrate": 8_000_000}) and proxy.is_heavy({"width": 1280, "height": 720, "codec": "h264", "bitrate": 60_000_000}), "HEVC / hohe Datenrate")
check(not proxy.is_heavy({}), "leere Angaben")
print("OK  Entscheidung")

# Quelle: 4K, 3 s, mit Ton, rot → blau (Bildinhalt prüfbar)
src = tmp / "px_4k.mp4"
sh("-f", "lavfi", "-i", "color=c=red:s=3840x2160:r=25:d=1.5", "-f", "lavfi", "-i", "color=c=blue:s=3840x2160:r=25:d=1.5", "-f", "lavfi", "-i", "sine=f=440:d=3",
   "-filter_complex", "[0][1]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src))
info = proxy.inspect(str(src))
check(info["width"] == 3840 and info["height"] == 2160 and info["has_audio"] and proxy.is_heavy(info), info)
check(proxy.existing(str(src)) == "", "noch kein Proxy")
check(proxy.proxy_path(str(src)) == proxy.proxy_path(str(src)), "Pfad stabil")

seen = []
pr = proxy.make(str(src), on_progress=seen.append)
check(os.path.isfile(pr) and pr.endswith(".mp4") and ".part" not in pr, pr)
check(seen and seen[-1] == 1.0, seen[-2:])
check(proxy.existing(str(src)) == pr, "wird gefunden")
check(proxy.make(str(src)) == pr, "zweiter Aufruf erzeugt nichts neu")
s = streams(pr)
v = next(x for x in s["streams"] if x["codec_type"] == "video")
a = [x for x in s["streams"] if x["codec_type"] == "audio"]
check(int(v["height"]) == 720 and int(v["width"]) == 1280, (v["width"], v["height"]))
check(a, "Ton vorhanden")
d0, d1 = float(streams(src)["format"]["duration"]), float(s["format"]["duration"])
check(abs(d0 - d1) < 0.15, f"gleiche Länge: {d0} / {d1}")
check(os.path.getsize(pr) < os.path.getsize(src) * 2, "Größe plausibel")
print("OK  Proxy erzeugen: 1280x720, Ton, gleiche Länge")

# kleine Quelle wird nicht vergrößert, ohne Ton geht auch
small = tmp / "px_small.mp4"
sh("-f", "lavfi", "-i", "color=c=green:s=320x180:r=25:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(small))
ps = proxy.make(str(small))
vs = next(x for x in streams(ps)["streams"] if x["codec_type"] == "video")
check(int(vs["height"]) == 180 and not [x for x in streams(ps)["streams"] if x["codec_type"] == "audio"], (vs["width"], vs["height"]))
print("OK  kleine Quelle ohne Ton")

# Ersetzen für die Vorschau
p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
p.clips = [Clip(str(src), 3.0, 0.0, 3.0, has_audio=True, width=3840, height=2160), Clip(str(small), 1.0, 0.0, 1.0)]
p.overlays = [OverlayClip(str(small), 1.0, 0.0, 1.0, start=0.5)]
before = p.to_json()
q = proxy.substitute(p)
check(p.to_json() == before, "Original-Projekt bleibt unverändert")
check(q.clips[0].path == pr and q.clips[1].path == ps and q.overlays[0].path == ps, [c.path for c in q.clips])
p.clips[0].stabilize = 40
check(proxy.substitute(p).clips[0].path == str(src), "Clip mit Stabilisierung behält das Original")
p.clips[0].stabilize = 0
check(proxy.candidates(p) == [], "alles hat schon einen Proxy")
new = tmp / "px_new.mp4"
sh("-f", "lavfi", "-i", "color=c=yellow:s=2560x1440:r=25:d=1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(new))
p.clips.append(Clip(str(new), 1.0, 0.0, 1.0))
check(proxy.candidates(p) == [str(new)], proxy.candidates(p))
print("OK  Ersetzen und Kandidaten")

# Vorschau mit Proxy zeigt dieselben Farben wie mit dem Original
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

p2 = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
p2.clips = [Clip(str(src), 3.0, 0.0, 3.0, has_audio=True, width=3840, height=2160)]
for label, proj in (("original", p2), ("proxy", proxy.substitute(p2))):
    for t, want in ((0.5, (255, 0, 0)), (2.0, (0, 0, 255))):
        out = tmp / f"px_{label}_{t}.png"
        stillframe.render(proj, t, str(out))
        im = np.array(Image.open(out).convert("RGB"))
        c = im[im.shape[0] // 2, im.shape[1] // 2].astype(int)
        check(all(abs(int(x) - y) <= 60 for x, y in zip(c, want)), f"{label} t={t}: {c}")
print("OK  Farben mit Proxy wie mit Original")

# Abbruch hinterlässt nichts
big = tmp / "px_cancel.mp4"
sh("-f", "lavfi", "-i", "testsrc2=s=3840x2160:r=25:d=6", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(big))
try:
    proxy.make(str(big), should_cancel=lambda: True)
except exporter.ExportError:
    pass
else:
    check(False, "Abbruch muss ExportError auslösen")
check(proxy.existing(str(big)) == "" and not list(proxy.proxy_dir().glob("*.part*")), "keine Reste nach Abbruch")
print("OK  Abbruch")

# fehlende Datei
try:
    proxy.make(str(tmp / "gibt_es_nicht.mp4"))
except proxy.ProxyError:
    pass
else:
    check(False, "fehlende Datei muss ProxyError auslösen")
print("OK  fehlende Datei")
print("ALLES OK")
