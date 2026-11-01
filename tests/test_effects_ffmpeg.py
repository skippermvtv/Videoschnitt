"""Rendert jeden Effekt kurz mit echtem FFmpeg (Testbild) und prüft, dass keine Fehler auftreten.

Aufruf:  python tests/test_effects_ffmpeg.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import effects as fx  # noqa: E402
from app.paths import find_binary  # noqa: E402


def main() -> int:
    ffmpeg = find_binary("ffmpeg")
    ctx = fx.Ctx(540, 960, 30)
    failed = []
    for eid in fx.REGISTRY:
        graph = ";".join(fx.build_graph([{"id": eid, "intensity": 70}], "0:v", "out", ctx))
        cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
               f"testsrc2=size=540x960:rate=30:duration=2", "-filter_complex",
               graph, "-map", "[out]", "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        status = "OK " if r.returncode == 0 and not r.stderr.strip() else "FEHLER"
        print(f"{status} {eid}")
        if status != "OK ":
            failed.append(eid)
            print("   ", graph[:300])
            print("   ", r.stderr.strip()[:400])
    # Zeitfenster
    graph = ";".join(fx.build_graph([{"id": "glitch", "intensity": 80, "start": 0, "end": 1}], "0:v", "out", ctx))
    r = subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30:duration=2",
                        "-filter_complex", graph, "-map", "[out]", "-f", "null", "-"], capture_output=True, text=True)
    print("OK  Zeitfenster" if r.returncode == 0 and not r.stderr.strip() else "FEHLER Zeitfenster\n" + r.stderr)
    if r.returncode != 0:
        failed.append("window")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
