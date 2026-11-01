"""End-to-End-Test: zwei Testclips -> Shorts-Export mit Look, Text, Geschwindigkeit."""
import subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, presets
from app.core.project import Clip, Project, TextLayer, probe
from app.paths import find_binary

out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
ff = find_binary("ffmpeg")
a = out_dir / "a_landscape.mp4"; b = out_dir / "b_vertical_noaudio.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=4",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(a)], check=True)
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "smptebars=size=720x1280:rate=30:duration=3",
                "-c:v", "libx264", str(b)], check=True)
clips = []
for p, speed, rev in ((a, 1.0, False), (b, 2.0, False)):
    i = probe(str(p))
    clips.append(Clip(str(p), i.duration, has_audio=i.has_audio, width=i.width, height=i.height, speed=speed, reverse=rev))
print("Clips:", [(c.name, c.has_audio, c.width, c.height, round(c.length, 2)) for c in clips])

for fmt in ("shorts", "youtube_16_9", "insta_square"):
    look = presets.get("looks", "glitch_intro")
    proj = Project(format_id=fmt, export_id=presets.get("formats", fmt)["default_export"], clips=clips,
                   effects=[{"id": e[0], "intensity": e[1], "start": e[2] if len(e) > 2 else None,
                             "end": e[3] if len(e) > 3 else None} for e in look["effects"]],
                   texts=[TextLayer(text="Hallo Welt – Größe äöü", start=0, end=4)], fade_in=0.3, fade_out=0.3)
    out = out_dir / f"out_{fmt}.mp4"
    cmd, total, tmp = exporter.build_command(proj, str(out))
    prog = []
    exporter.run(cmd, total, prog.append)
    info = probe(str(out))
    print(f"{fmt}: {info.width}x{info.height}, {info.duration:.2f}s (erwartet {total:.2f}s), audio={info.has_audio}, progress_calls={len(prog)}")
    assert (info.width, info.height) == (presets.get("formats", fmt)["width"], presets.get("formats", fmt)["height"])
    assert abs(info.duration - total) < 0.3
print("ALLES OK ->", out_dir)
