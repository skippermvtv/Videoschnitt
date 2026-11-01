"""Übergänge mit echtem FFmpeg: Länge, Ton bleibt durchgehend, alle Übergänge der Liste lassen sich rendern."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, presets  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def mk(name, src, freq, dur):
    f = tmp / name
    sh("-f", "lavfi", "-i", f"{src}=size=320x180:rate=25:duration={dur}", "-f", "lavfi",
       "-i", f"sine=frequency={freq}:duration={dur}", "-af", "volume=4", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(f))
    return f


def clips(files, durs):
    out = []
    for f, d in zip(files, durs):
        i = probe(str(f))
        out.append(Clip(str(f), i.duration, has_audio=i.has_audio, width=i.width, height=i.height))
    return out


def render(p, name):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    info = probe(str(out))
    assert abs(info.duration - p.duration) < 0.35, (name, info.duration, p.duration)
    assert abs(total - p.duration) < 0.1, (name, total, p.duration)
    return out


def level(path, t0, t1, freq=440):
    r = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True, check=True)
    x = np.frombuffer(r.stdout, dtype=np.float32)[int(t0 * 16000):int(t1 * 16000)]
    x = x * np.hanning(len(x))
    spec = np.abs(np.fft.rfft(x)) / len(x) * 4
    f = np.fft.rfftfreq(len(x), 1 / 16000)
    return float(spec[(f > freq - 20) & (f < freq + 20)].max())


def main() -> int:
    a, b, c = mk("a.mp4", "testsrc2", 440, 3), mk("b.mp4", "smptebars", 440, 3), mk("c.mp4", "testsrc2", 440, 3)
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = clips([a, b, c], [3, 3, 3])
    p.clips[0].transition, p.clips[0].transition_dur = "fade", 1.0     # Überblendung
    # Clip 2 -> 3: harter Schnitt (gemischt)
    assert abs(p.duration - 8.0) < 0.1 and abs(p.clip_start(1) - 2.0) < 1e-6 and abs(p.clip_start(2) - 5.0) < 0.1
    out = render(p, "mixed")
    assert level(out, 1.9, 3.1) > 0.3, "Ton bricht in der Überblendung ab"
    assert level(out, 5.0, 7.5) > 0.3
    print("OK  Überblendung + harter Schnitt gemischt, Länge", round(p.duration, 2))

    # zu lange Übergangsdauer wird begrenzt
    p.clips[0].transition_dur = 10.0
    assert p.duration > 6.0 and p.overlap_after(0) < 1.5
    render(p, "clamped")
    print("OK  Übergangsdauer wird begrenzt")

    # letzter Clip / einzelner Clip: Übergang ohne Wirkung
    q = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    q.clips = clips([a], [3]); q.clips[0].transition = "fade"
    assert abs(q.duration - 3.0) < 0.1
    render(q, "single")

    # getrennter Ton folgt dem Clip über die Überlappung
    p.clips[0].transition_dur = 1.0
    d = p.detach_audio(1)
    assert abs(d.start - 2.0) < 1e-6
    p.clips.reverse(); p.sync_linked()
    print("OK  Einzelclip, getrennter Ton")

    # alle Übergänge der Liste
    s1, s2 = mk("s1.mp4", "testsrc2", 440, 1.5), mk("s2.mp4", "smptebars", 440, 1.5)
    ids = [t["id"] for t in presets.load("transitions")]
    assert len(ids) >= 25
    for tid in ids:
        r = Project(format_id="youtube_16_9", export_id="youtube_1080p")
        r.clips = clips([s1, s2], [1.5, 1.5])
        r.clips[0].transition, r.clips[0].transition_dur = tid, 0.5
        render(r, f"t_{tid}")
    print(f"OK  alle {len(ids)} Übergänge rendern")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
