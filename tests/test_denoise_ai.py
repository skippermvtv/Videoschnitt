"""KI-Rauschentfernung (RNNoise über FFmpeg arnndn): Filterkette, Pfad-Schreibweise, echte Wirkung im Export, Modell fehlt."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
tmp.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import audiofix, exporter  # noqa: E402
from app.core.project import AudioClip, Clip, Project  # noqa: E402
from app.paths import find_binary  # noqa: E402

FF = find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


check(audiofix.model_path().is_file() and audiofix.model_path().stat().st_size > 100_000, "Modell wird mitgeliefert")
check(audiofix.ai_filter(0) == "" and audiofix.chain() == "", "aus = keine Kette")
f = audiofix.ai_filter(80)
check(f.startswith("arnndn=m='") and f.endswith("':mix=0.80"), f)
check(audiofix.chain(0, 0, None, 50).startswith("arnndn="), "KI zuerst")
check(audiofix.chain(40, 30, -45, 100).split(",")[0].startswith("arnndn=") and "afftdn" in audiofix.chain(40, 30, -45, 100), "alle drei")
check(audiofix._esc("C:\\Users\\Max Muster\\sh.rnnn") == "C\\:/Users/Max Muster/sh.rnnn", audiofix._esc("C:\\Users\\Max Muster\\sh.rnnn"))
print("OK  Filterkette")

# Modell fehlt → Ton bleibt unverändert, kein Fehler
orig = audiofix.model_path
audiofix.model_path = lambda: tmp / "gibt_es_nicht.rnnn"
check(audiofix.ai_filter(100) == "" and audiofix.chain(0, 0, None, 100) == "", "ohne Modell leer")
audiofix.model_path = orig
print("OK  Modell fehlt")

# Echte Wirkung: Video mit nichts als Rauschen im Ton → mit KI-Rauschentfernung deutlich leiser
vid = tmp / "dnai_noise.mp4"
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=10:d=3", "-f", "lavfi",
                "-i", "anoisesrc=d=3:c=pink:a=0.3:r=48000", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)


def mean_volume(path: Path) -> float:
    r = subprocess.run([FF, "-hide_banner", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)", r.stderr)
    check(m is not None, r.stderr[-300:])
    return float(m.group(1))


def render(level: int, name: str) -> Path:
    p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
    p.clips = [Clip(str(vid), 3.0, has_audio=True, width=160, height=90, denoise_ai=level)]
    out = tmp / name
    cmd, total, tdir = exporter.build_command(p, str(out), draft=True, preview_height=90)
    r = subprocess.run(cmd, capture_output=True, text=True)
    check(r.returncode == 0 and out.is_file(), r.stderr[-400:])
    return out


plain, ai = render(0, "dnai_plain.mp4"), render(100, "dnai_ai.mp4")
v0, v1 = mean_volume(plain), mean_volume(ai)
check(v1 < v0 - 6.0, f"KI-Rauschentfernung wirkt kaum: ohne {v0} dB, mit {v1} dB")
half = mean_volume(render(50, "dnai_half.mp4"))
check(v1 - 0.5 <= half <= v0 + 0.5, f"50 % liegt nicht zwischen 0 und 100 %: {v1} / {half} / {v0}")
print(f"OK  Wirkung im Export: {v0:.1f} dB → {v1:.1f} dB (50 %: {half:.1f} dB)")

# Audioblock (Musik/Sprache auf A1–A3) bekommt dieselbe Kette
from app.core import audiomix  # noqa: E402
wav = tmp / "dnai_noise.wav"
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=3:c=pink:a=0.3:r=48000", str(wav)], check=True)
p = Project(format_id="youtube_16_9", export_id="fast_draft", layout="fill")
p.clips = [Clip(str(vid), 3.0, has_audio=False, width=160, height=90)]
p.audio_clips = [AudioClip(str(wav), 3.0, denoise_ai=100)]
inputs, lines = audiomix.build_audio(p, 3.0, 1)
check("arnndn" in " ".join(lines), "Audioblock ohne arnndn")
p.audio_clips[0].denoise_ai = 0
check("arnndn" not in " ".join(audiomix.build_audio(p, 3.0, 1)[1]), "ohne Regler kein arnndn")
print("OK  Audioblock")
print("ALLES OK")
