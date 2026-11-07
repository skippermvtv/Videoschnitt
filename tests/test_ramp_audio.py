"""Geschwindigkeitskurve: der Ton darf an den Abschnittsgrenzen keine Lücken (Stille) bekommen.
Hintergrund: atempo liefert bei langsamem Tempo bis ~50 ms zu wenig Ton, concat füllte das mit Stille."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import exporter, speedramp as sr  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")
src = tmp / "s.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=8", "-f", "lavfi",
                "-i", "aevalsrc=0.5*sin(2*PI*440*t):d=8:s=48000", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "256k", str(src)], check=True)
info = probe(str(src))


def gaps(x, sr_=48000):
    quiet = np.abs(x) < 0.004
    runs, i = [], 0
    while i < len(x):
        if quiet[i]:
            j = i
            while j < len(x) and quiet[j]:
                j += 1
            if j - i > 40:                      # > ~1 ms Stille mitten im Sinus
                runs.append((round(i / sr_, 3), round((j - i) / sr_ * 1000, 1)))
            i = j
        else:
            i += 1
    return runs


for name, pts in [("langsam", [[0, 1], [40, 1], [55, 0.3], [70, 1], [100, 2]]), ("schnell", [[0, 1], [50, 4], [100, 1]]),
                  ("sehr langsam", [[0, 0.2], [100, 0.2]])]:
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(src), info.duration, has_audio=True, width=info.width, height=info.height)]
    sr.apply(p, 0, pts)
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True, preview_height=180)
    exporter.run(cmd, total)
    x = np.frombuffer(subprocess.run([ff, "-v", "error", "-i", str(out), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                                     capture_output=True, check=True).stdout, dtype=np.float32).astype(float)
    g = [r for r in gaps(x) if r[0] < len(x) / 48000 - 0.3]          # die letzten Millisekunden (Dateiende) zählen nicht
    if g:
        print("FEHLER: Tonlücken", name, g)
        sys.exit(1)
    check = lambda c, m: (print("FEHLER:", m), sys.exit(1)) if not c else None  # noqa: E731
    d2 = np.abs(np.diff(x, 2))
    body = d2[: int((len(x) / 48000 - 0.3) * 48000)]                    # ohne das Dateiende
    check(float(body.max()) < 0.05, f"{name}: Knacken an einer Schnittstelle (2. Differenz {body.max():.3f}, reiner Sinus ~0.008)")
    print(f"OK  {name}: {len(x) / 48000:.2f} s, keine Tonlücken, kein Knacken (max {body.max():.4f})")
print("ALLES OK")
