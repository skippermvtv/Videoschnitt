"""KI-Hochskalieren: Planung, Paket-Auswahl und -Installation, Ablauf in Stücken mit Ersatzprogramm (Bildlage, Ton, Dauer),
Abbruch, Fehler, schwarze Ausgabe. Das echte Real-ESRGAN braucht eine Vulkan-Grafikkarte und wird hier nicht ausgeführt."""
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
tmp.mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(tmp / "appdata_up")                    # eigener Benutzerordner, nichts vom echten Programm anfassen
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import upscale  # noqa: E402
from app.core.project import Clip, Project  # noqa: E402
from app.core.whisper_setup import Cancelled  # noqa: E402
from app.paths import find_binary  # noqa: E402

FF, FP = find_binary("ffmpeg"), find_binary("ffprobe")
FAKE = str(Path(__file__).resolve().parent / "fake_esrgan.py")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


def prog(*extra):
    return [sys.executable, FAKE, *extra]


# --- Planung
check(upscale.plan(1080, 2160) == (2, 2160), upscale.plan(1080, 2160))
check(upscale.plan(1080, 1440) == (2, 1440), "1080 → 1440 über Faktor 2, dann verkleinern")
check(upscale.plan(720, 2160) == (3, 2160), upscale.plan(720, 2160))
check(upscale.plan(540, 2160) == (4, 2160), upscale.plan(540, 2160))
check(upscale.plan(1080, 2160, "photo") == (4, 2160), "Foto-Modell nur 4-fach")
for bad in ((2160, 2160), (2160, 1440), (0, 1440)):
    try:
        upscale.plan(*bad)
        check(False, f"hätte scheitern müssen: {bad}")
    except upscale.UpscaleError:
        pass
try:
    upscale.plan(360, 2160)                                         # 6-fach: mit dem Modell nicht möglich
    check(False, "360 → 2160")
except upscale.UpscaleError as exc:
    check("höchstens 4-fach" in str(exc), exc)
print("OK  Planung")

# --- Paket: Auswahl und Installation (lokale Datei statt Internet)
rel = {"assets": [{"name": "realesrgan-ncnn-vulkan-20220424-ubuntu.zip", "browser_download_url": "u1"},
                  {"name": "realesrgan-ncnn-vulkan-20220424-windows.zip", "browser_download_url": "u2"}]}
check(upscale.pick_asset(rel) == ("u2", "realesrgan-ncnn-vulkan-20220424-windows.zip"), upscale.pick_asset(rel))
check(upscale.pick_asset({"assets": []}) is None and upscale.pick_asset({}) is None, "kein Paket")
check(upscale.find_program() is None, "vorher nichts eingerichtet")
pkg = tmp / "up_pkg.zip"
with zipfile.ZipFile(pkg, "w") as z:
    z.writestr("realesrgan-ncnn-vulkan-20220424-windows/" + upscale.EXE_NAME, b"MZ" + b"0" * 200)
    z.writestr("realesrgan-ncnn-vulkan-20220424-windows/models/realesr-animevideov3-x2.param", "x")
    z.writestr("realesrgan-ncnn-vulkan-20220424-windows/models/realesr-animevideov3-x2.bin", "x")
exe = upscale.install(pkg.as_uri(), min_bytes=100)
check(exe.is_file() and upscale.find_program() == exe, exe)
check(upscale.models_ok(exe, "realesr-animevideov3") and not upscale.models_ok(exe, "realesrgan-x4plus"), "Modelle")
print("OK  Paket")

# --- Ablauf mit Ersatzprogramm: 3 s, 25 fps, 320×180 → 640×360, in 4 Stücken zu 20 Bildern (75 Bilder)
src = tmp / "up_src.mp4"
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "25", "-c:a", "aac", "-shortest", str(src)], check=True)


def vinfo(path):
    r = subprocess.run([FP, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate",
                        "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    return d["streams"][0], float(d["format"]["duration"])


def has_audio(path):
    r = subprocess.run([FP, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def frame_bytes(path, t, w, h):
    r = subprocess.run([FF, "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={w}:{h}:flags=lanczos,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    return r.stdout


def mad(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


progress = []
out = tmp / "up_out360.mp4"
res = upscale.upscale_range(str(src), 0.0, 0.0, 360, out, program=prog(), progress=lambda f, t: progress.append(f), chunk_frames=20, work_root=tmp)
check(res == out and out.is_file(), res)
vs, dur = vinfo(out)
check((vs["width"], vs["height"]) == (640, 360), vs)
check(abs(int(vs["nb_read_frames"]) - 75) <= 2 and abs(dur - 3.0) < 0.15, (vs, dur))
check(has_audio(out), "Ton fehlt")
check(progress and progress[-1] == 1.0 and progress == sorted(progress), progress)
for t in (0.2, 0.9, 1.5, 2.4):                                      # Bildlage über die Stückgrenzen (0,8 s, 1,6 s, 2,4 s)
    d = mad(frame_bytes(src, t, 640, 360), frame_bytes(out, t, 640, 360))
    check(d < 8.0, f"Bild bei {t} s weicht ab ({d:.1f})")
print(f"OK  Ablauf in Stücken: {vs['width']}x{vs['height']}, {vs['nb_read_frames']} Bilder, {dur:.2f} s, mit Ton")
leftovers = list(tmp.glob("fate_upscale_*"))
check(not leftovers, f"Arbeitsordner nicht aufgeräumt: {leftovers}")

# Ziel nicht ganzzahlig: 180 → 270 (Faktor 2, dann auf 270 verkleinern, Breite gerade)
out2 = tmp / "up_out270.mp4"
upscale.upscale_range(str(src), 0.0, 0.0, 270, out2, program=prog(), chunk_frames=100, work_root=tmp)
vs2, _ = vinfo(out2)
check(vs2["height"] == 270 and vs2["width"] % 2 == 0 and abs(vs2["width"] - 480) <= 2, vs2)

# Ausschnitt 1,0–2,0 s: genau 25 Bilder, Quellstelle stimmt
out3 = tmp / "up_out_part.mp4"
upscale.upscale_range(str(src), 1.0, 2.0, 360, out3, program=prog(), chunk_frames=20, work_root=tmp)
vs3, d3 = vinfo(out3)
check(abs(int(vs3["nb_read_frames"]) - 25) <= 1 and abs(d3 - 1.0) < 0.12, (vs3, d3))
check(mad(frame_bytes(src, 1.4, 640, 360), frame_bytes(out3, 0.4, 640, 360)) < 8.0, "Ausschnitt zeigt die falsche Stelle")
print("OK  Zielhöhe 270 und Ausschnitt")

# --- Clip auf die neue Datei umstellen
p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
p.clips = [Clip(str(src), 3.0, in_pt=1.0, out_pt=2.0, has_audio=True, width=320, height=180, speed=1.5)]
upscale.apply_to_clip(p, 0, str(out3))
c = p.clips[0]
check(c.path == str(out3) and c.in_pt == 0.0 and abs(c.out_pt - d3) < 1e-6 and c.height == 360 and c.speed == 1.5, c)
print("OK  Clip umgestellt")

# --- Abbruch, Fehler, schwarze Ausgabe, zu wenig Platz
n = {"k": 0}


def cancel_after_first():
    n["k"] += 1
    return n["k"] > 12


try:
    upscale.upscale_range(str(src), 0.0, 0.0, 360, tmp / "up_cancel.mp4", program=prog(), cancelled=cancel_after_first, chunk_frames=20, work_root=tmp)
    check(False, "Abbruch")
except Cancelled:
    pass
check(not (tmp / "up_cancel.mp4").exists() and not (tmp / "up_cancel.part.mp4").exists() and not list(tmp.glob("fate_upscale_*")), "Reste nach Abbruch")
for mode, expect in (("fail", "Vulkan"), ("half", "nur"), ("black", "schwarze")):
    try:
        upscale.upscale_range(str(src), 0.0, 0.0, 360, tmp / f"up_{mode}.mp4", program=prog("--mode", mode), chunk_frames=100, work_root=tmp)
        check(False, f"{mode} hätte scheitern müssen")
    except upscale.UpscaleError as exc:
        check(expect in str(exc), (mode, str(exc)))
    check(not (tmp / f"up_{mode}.mp4").exists() and not list(tmp.glob("fate_upscale_*")), f"Reste nach {mode}")
ok, free = upscale.free_space_ok(tmp, 10 ** 9)
check(ok is False and free > 0, (ok, free))
print("OK  Abbruch und Fehlerfälle")

out_p = upscale.output_path(str(src), 1.0, 2.0, 2160, "video")
check(out_p.parent.name == "upscaled" and out_p.suffix == ".mp4" and out_p != upscale.output_path(str(src), 1.0, 2.0, 1440, "video"), out_p)
print("ALLES OK")
