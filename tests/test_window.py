"""Zeitfenster-Projekt: das Fenster zeigt dasselbe Bild und dieselbe Länge wie das volle Projekt (echtes FFmpeg)."""
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, window  # noqa: E402
from app.core.project import AudioClip, Clip, OverlayClip, Project, SubtitleCue, TextLayer, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
H_PREV = 180


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def source(name, dur, hue):
    f = tmp / name
    sh("-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={dur}", "-f", "lavfi", "-i", f"sine=frequency={300 + hue}:duration={dur}",
       "-vf", f"hue=h={hue}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f))
    return f


def clip(path, **kw):
    i = probe(str(path))
    return Clip(str(path), i.duration, has_audio=True, width=i.width, height=i.height, **kw)


def render(p, name, **kw):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True, preview_height=H_PREV, **kw)
    exporter.run(cmd, total)
    return out


def frame(video, t):
    png = tmp / "fr.png"
    sh("-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(png))
    return np.array(Image.open(png).convert("RGB")).astype(float)


def diff(a, b):
    return float(np.abs(a - b).mean())


def build():
    s1, s2, s3, s4, s5 = (source(f"s{i}.mp4", d, h) for i, (d, h) in enumerate(((4, 0), (3, 60), (5, 120), (3, 180), (4, 240)), 1))
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [clip(s1, transition="fade", transition_dur=0.8), clip(s2), clip(s3, speed=2.0, transition="wipeleft", transition_dur=0.6),
               clip(s4, reverse=True), clip(s5, keyframes=[{"t": 0, "zoom": 100, "x": 0, "y": 0, "rot": 0},
                                                         {"t": 1, "zoom": 160, "x": 20, "y": 0, "rot": 0}])]
    p.clips[1].in_pt = 0.5
    p.effects = [{"id": "bw", "intensity": 100, "start": 3.0, "end": 6.5}, {"id": "vignette", "intensity": 60}]
    p.texts = [TextLayer(text="Hallo", start=4.0, end=8.0, size_pct=12.0)]
    p.subtitles = [SubtitleCue(0.5, 2.0, "eins"), SubtitleCue(9.0, 11.0, "zwei")]
    img = tmp / "o.png"
    sh("-f", "lavfi", "-i", "color=c=0xe01010:s=200x120", "-frames:v", "1", str(img))
    p.overlays = [OverlayClip(str(img), 5.0, 0.0, 3.0, start=2.0, is_image=True, x_pct=75, y_pct=25, size_pct=30)]
    mus = tmp / "m.wav"
    sh("-f", "lavfi", "-i", "sine=frequency=500:duration=12", str(mus))
    p.audio_clips = [AudioClip(str(mus), 12.0, 0.0, 12.0, start=1.0, track=2, volume=0.5)]
    return p


def main() -> int:
    p = build()
    total = p.duration
    print(f"Projektlänge {total:.2f} s, Clip-Starts", [round(p.clip_start(i), 2) for i in range(len(p.clips))])
    full = render(p, "full")

    # --- Fenster-Grenzen: nie mitten in einen Übergang
    S = [p.clip_start(i) for i in range(len(p.clips))]
    ends = [S[i] + p.clips[i].length for i in range(len(p.clips))]
    for t in (0, 0.2, S[1] + 0.3, S[1] + 0.9, ends[0] - 0.2, 5.0, 8.0, total - 0.4):
        w0 = window.snap_start(p, t)
        assert 0.0 <= w0 <= t + 1e-6, (t, w0)
        w1 = window.snap_end(p, min(total, t + 3))
        assert w1 >= min(total, t + 3) - 1e-6 and w1 <= total + 1e-6
    print("OK  Fenstergrenzen")

    # --- Bildvergleich: Fenster = volles Projekt, an vielen Stellen (auch in Übergängen und Effektgrenzen)
    rnd = random.Random(7)
    starts = [0.0, 1.3, S[1] + 0.4, S[1] + 0.9, S[2] + 0.3, 3.1, 5.2, 7.7, ends[2] - 0.3, total - 3.5]
    starts += [round(rnd.uniform(0, total - 2), 2) for _ in range(3)]
    worst = 0.0
    oks, bads = [], []
    for n, t0 in enumerate(starts):
        t0 = max(0.0, min(t0, total - 2.0))
        wp, delta, ln = window.project_window(p, t0, 2.5)
        win = render(wp, f"win{n}", start=delta, max_seconds=ln)
        assert abs(probe(str(win)).duration - ln) < 0.4, (t0, probe(str(win)).duration, ln)
        for rel in (0.1, 1.0, ln - 0.3):
            a, b = frame(win, rel), frame(full, t0 + rel)
            d_ok = diff(a, b)
            d_bad = diff(a, frame(full, min(total - 0.1, t0 + rel + 1.2)))
            worst = max(worst, d_ok)
            oks.append(d_ok)
            bads.append(d_bad)
            assert d_ok < 14.0, f"Fenster bei {t0:.2f}+{rel:.2f} weicht ab: {d_ok:.1f}"
        if wp.clips and len(wp.clips) < len(p.clips):
            pass
        print(f"   t0={t0:5.2f}  Fenster {window.snap_start(p, t0):5.2f}…  Clips {len(wp.clips)}/{len(p.clips)}  Effekte {len(wp.effects)}"
              f"  Texte {len(wp.texts)}  Overlays {len(wp.overlays)}")
    assert np.mean(oks) < 5.0 and np.mean(bads) > 1.5 * np.mean(oks), (np.mean(oks), np.mean(bads))      # der Test kann falsche Zeiten erkennen
    print(f"OK  Fenster = Vollprojekt (schlechtester Unterschied {worst:.1f}, Mittel {np.mean(oks):.1f} gegen {np.mean(bads):.1f} bei falscher Zeit)")

    # --- Ton vorhanden und Länge stimmt
    wp, delta, ln = window.project_window(p, 6.0, 2.0)
    out = render(wp, "audio", start=delta, max_seconds=ln)
    assert probe(str(out)).has_audio
    print("OK  Ton im Fenster")

    # --- Fenster kleiner als das Projekt: weniger Clips und Texte
    wp, _d, _l = window.project_window(p, 0.2, 1.0)
    assert len(wp.clips) < len(p.clips) and not wp.subtitles[1:] and len(wp.audio_clips) == 1
    assert wp.fade_out == 0.0
    # Randfälle
    for t0, ln_ in ((-5, 3), (999, 3), (0, 0.1), (0, 9999)):
        wp, delta, ln = window.project_window(p, t0, ln_)
        assert wp.clips and delta >= 0 and ln > 0
    empty, d0, l0 = window.project_window(Project(), 0, 3)
    assert not empty.clips and l0 == 0.0
    print("OK  Randfälle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
