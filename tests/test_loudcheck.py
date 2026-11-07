"""Lautheit der fertigen Datei nachmessen: Auswertung des ebur128-Texts, echte Messung, Beschreibung."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import loudcheck as lc  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


SUMMARY = """[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -23.4 LUFS
    Threshold: -33.5 LUFS

  Loudness range:
    LRA:         3.2 LU
"""
check(lc.parse_summary(SUMMARY) == -23.4, "Summary lesen")
check(lc.parse_summary("kein Ergebnis") is None and lc.parse_summary("") is None and lc.parse_summary(None) is None, "ohne Summary")
check(lc.parse_summary("  I:         -14.0 LUFS\n" + SUMMARY) == -23.4, "letzter Treffer zählt")
print("OK  Auswertung")

check(lc.describe(None) == "" and lc.describe(None, -14.0) == "", "nichts gemessen")
check(lc.describe(-13.24) == "Lautheit: −13,2 LUFS", lc.describe(-13.24))
check(lc.describe(-13.24, -14.0) == "Lautheit: −13,2 LUFS (Ziel −14,0)", lc.describe(-13.24, -14.0))
print("OK  Beschreibung")

ff = paths.find_binary("ffmpeg")
loud = tmp / "loud.wav"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*440*t):d=4:s=48000", str(loud)], check=True)
quiet = tmp / "quiet.wav"
subprocess.run([ff, "-v", "error", "-y", "-i", str(loud), "-af", "volume=-20dB", str(quiet)], check=True)
a, b = lc.measure(str(loud)), lc.measure(str(quiet))
check(a is not None and b is not None and abs((a - b) - 20.0) < 0.3, f"20 dB Unterschied gemessen: {a} / {b}")
check(-12 < a < -5, f"Sinus 0,5 Amplitude ≈ −9 LUFS, gemessen {a}")
print(f"OK  Messung: {a:.1f} und {b:.1f} LUFS")

silent = tmp / "silent.wav"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "2", str(silent)], check=True)
check(lc.measure(str(silent)) is None, "Stille → None")
novid = tmp / "novideo.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1:r=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(novid)], check=True)
check(lc.measure(str(novid)) is None, "ohne Tonspur → None")
check(lc.measure(str(tmp / "gibtsnicht.mp4")) is None, "fehlende Datei → None")
print("OK  Sonderfälle")
print("ALLES OK")
