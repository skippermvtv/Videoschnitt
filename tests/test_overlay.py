"""Standbilder und Bild-in-Bild mit echtem FFmpeg (Pixelprüfung der Ausgabe)."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter  # noqa: E402
from app.core.project import (AudioClip, Clip, IMAGE_MAX, OverlayClip, Project, probe,  # noqa: E402
                              is_image_path)
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def solid_video(name, color, dur, size="320x180", audio=False):
    f = tmp / name
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={size}:r=25:d={dur}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-af", "volume=4", "-c:a", "aac"]
    sh(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(f))
    return f


def solid_image(name, color, size="200x120"):
    f = tmp / name
    sh("-f", "lavfi", "-i", f"color=c={color}:s={size}", "-frames:v", "1", str(f))
    return f


def clip_of(path):
    i = probe(str(path))
    c = Clip(str(path), IMAGE_MAX if i.is_image else i.duration, has_audio=i.has_audio, width=i.width,
             height=i.height, is_image=i.is_image)
    if i.is_image:
        c.out_pt = i.duration
    return c


def render(p, name, **kw):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True, **kw)
    exporter.run(cmd, total)
    return out, total


def pixel(video, t, fx, fy):
    png = tmp / "f.png"
    sh("-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(png))
    im = np.array(Image.open(png).convert("RGB"))
    h, w, _ = im.shape
    return tuple(int(v) for v in im[int(h * fy), int(w * fx)])


def near(c, ref, tol=45):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def base():
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [clip_of(solid_video("blue.mp4", "0x1020e0", 4, audio=True))]
    return p


def main() -> int:
    assert is_image_path("a.PNG") and not is_image_path("a.mp4")

    # 1) Standbild als Hauptclip (rot, 2 s) + Video (blau)
    img = solid_image("red.png", "0xe01010")
    i = probe(str(img)); assert i.is_image and i.duration == 5.0 and not i.has_audio
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    c = clip_of(img); c.out_pt = 2.0
    p.clips = [c, clip_of(solid_video("blue.mp4", "0x1020e0", 4, audio=True))]
    assert abs(p.duration - 6.0) < 0.01
    out, total = render(p, "still")
    info = probe(str(out)); assert abs(info.duration - 6.0) < 0.3 and info.has_audio
    assert near(pixel(out, 1.0, 0.5, 0.5), (224, 16, 16)), pixel(out, 1.0, 0.5, 0.5)
    assert near(pixel(out, 4.0, 0.5, 0.5), (16, 32, 224))
    print("OK  Standbild als Clip (Länge, Farbe, Ton ergänzt)")

    # 2) Overlay (Bild) oben rechts, Startzeit 1 s, Länge 2 s
    p = base()
    p.overlays.append(OverlayClip(str(solid_image("o.png", "0xe01010")), IMAGE_MAX, 0.0, 2.0, start=1.0, is_image=True,
                                  x_pct=75, y_pct=25, size_pct=30))
    out, total = render(p, "ov1")
    assert abs(probe(str(out)).duration - 4.0) < 0.3
    assert near(pixel(out, 0.4, 0.75, 0.25), (16, 32, 224)), "vor dem Start darf nichts zu sehen sein"
    assert near(pixel(out, 2.0, 0.75, 0.25), (224, 16, 16)), pixel(out, 2.0, 0.75, 0.25)
    assert near(pixel(out, 2.0, 0.25, 0.75), (16, 32, 224)), "Rest des Bildes bleibt blau"
    assert near(pixel(out, 3.5, 0.75, 0.25), (16, 32, 224)), "nach dem Ende darf nichts zu sehen sein"
    print("OK  Bild-in-Bild: Zeit, Position")

    # 3) Deckkraft 50 %
    p.overlays[0].opacity = 50
    out, _ = render(p, "ov2")
    c2 = pixel(out, 2.0, 0.75, 0.25)
    assert 90 < c2[0] < 160 and 90 < c2[2] < 160, c2
    print("OK  Deckkraft", c2)

    # 4) Rahmen, Ein-/Ausblenden, Größe
    p.overlays[0].opacity = 100; p.overlays[0].border = True; p.overlays[0].fade_in = 0.5; p.overlays[0].fade_out = 0.5
    render(p, "ov3")
    print("OK  Rahmen und Blenden rendern")

    # 5) Overlay-Video länger als das Hauptvideo verlängert den Export nicht; Start hinter dem Ende wird übersprungen
    p = base()
    ovv = clip_of(solid_video("ovv.mp4", "0x20c020", 5))
    p.overlays = [OverlayClip(str(ovv.path), ovv.duration, 0.0, ovv.duration, start=3.0, size_pct=40),
                  OverlayClip(str(ovv.path), ovv.duration, 0.0, 2.0, start=10.0)]
    out, total = render(p, "ov4")
    assert abs(probe(str(out)).duration - 4.0) < 0.3, probe(str(out)).duration
    assert near(pixel(out, 3.6, 0.75, 0.25), (32, 192, 32)), pixel(out, 3.6, 0.75, 0.25)
    print("OK  Overlay-Video wird gekürzt, spätes Overlay übersprungen")

    # 6) Zusammen mit Musik und Overlays: Eingänge stimmen (Ton bleibt hörbar)
    p.audio_clips.append(AudioClip(_music(), 2.0, start=0.0, track=2, loop=True))
    out, _ = render(p, "ov5")
    r = subprocess.run([ff, "-v", "error", "-i", str(out), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True)
    x = np.frombuffer(r.stdout, dtype=np.float32)[16000:48000]
    assert float(np.abs(x).max()) > 0.2
    print("OK  Overlay + Musik zusammen")

    # 7) Speichern/Laden, altes Projekt
    f = tmp / "t.cforge"; p.save(str(f))
    q = Project.load(str(f)); assert len(q.overlays) == 2 and q.overlays[0].size_pct == 40
    import json
    d = json.loads(f.read_text(encoding="utf-8")); d.pop("overlays"); d["clips"][0].pop("is_image", None)
    f.write_text(json.dumps(d), encoding="utf-8")
    assert Project.load(str(f)).overlays == []
    print("OK  Speichern/Laden")
    print("ALLES OK ->", tmp)
    return 0


def _music():
    f = tmp / "m.wav"
    sh("-f", "lavfi", "-i", "sine=frequency=1000:duration=2", "-af", "volume=4", str(f))
    return str(f)


if __name__ == "__main__":
    sys.exit(main())
