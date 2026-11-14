"""Ersatz für realesrgan-ncnn-vulkan in den Tests (gleiche Aufrufart): vergrößert jedes PNG eines Ordners mit FFmpeg (Lanczos).
Zusätzlich: --mode fail (bricht ab), --mode black (schreibt schwarze Bilder), --mode half (schafft nur die Hälfte)."""
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
opt = {}
i = 0
while i < len(args):
    if args[i].startswith("-") and i + 1 < len(args):
        opt[args[i]] = args[i + 1]
        i += 2
    else:
        i += 1
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.paths import find_binary  # noqa: E402

mode = opt.get("--mode", "")
src, dst, scale = Path(opt["-i"]), Path(opt["-o"]), int(opt.get("-s", "4"))
files = sorted(src.glob("*.png"))
if mode == "fail":
    print("vkCreateInstance failed -3")
    sys.exit(1)
if mode == "half":
    files = files[:len(files) // 2]
for f in files:
    vf = f"scale=iw*{scale}:ih*{scale}:flags=lanczos"
    if mode == "black":
        vf += ",lutrgb=r=0:g=0:b=0"
    subprocess.run([find_binary("ffmpeg"), "-v", "error", "-y", "-i", str(f), "-vf", vf, str(dst / f.name)], check=True)
sys.exit(1 if mode == "half" else 0)
