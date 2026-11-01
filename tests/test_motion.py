"""Zuschneiden, Drehen, Spiegeln und Keyframe-Bewegung mit echtem FFmpeg (Pixelprüfung)."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, presets  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def quad_video(dur=4):
    """320x180: links rot, rechts blau; oben links zusätzlich gelber Block."""
    f = tmp / "quad.mp4"
    sh("-f", "lavfi", "-i", f"color=c=0xe01010:s=160x180:r=25:d={dur}", "-f", "lavfi", "-i", f"color=c=0x1010e0:s=160x180:r=25:d={dur}",
       "-filter_complex", "[0][1]hstack,drawbox=x=0:y=0:w=40:h=40:color=0xf0e010:t=fill[v]", "-map", "[v]",
       "-c:v", "libx264", "-pix_fmt", "yuv444p", str(f))
    return f


def proj(**kw):
    f = quad_video()
    i = probe(str(f))
    c = Clip(str(f), i.duration, has_audio=False, width=i.width, height=i.height, **kw)
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p"); p.clips = [c]
    return p


def frame(p, t, name):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    png = tmp / f"{name}.png"
    sh("-ss", f"{t}", "-i", str(out), "-frames:v", "1", str(png))
    return np.array(Image.open(png).convert("RGB")).astype(int)


def at(im, fx, fy):
    h, w, _ = im.shape
    return tuple(im[int(h * fy), int(w * fx)])


def near(c, ref, tol=60):
    return all(abs(int(a) - b) <= tol for a, b in zip(c, ref))


RED, BLUE, YEL = (224, 16, 16), (16, 16, 224), (240, 224, 16)


def main() -> int:
    # Gespiegelt: Rot rechts
    im = frame(proj(flip_h=True), 1.0, "flip")
    assert near(at(im, 0.9, 0.5), RED) and near(at(im, 0.1, 0.5), BLUE), (at(im, .9, .5), at(im, .1, .5))
    # Zuschneiden: linke 50 % weg -> nur Blau
    im = frame(proj(crop_l=50), 1.0, "crop")
    assert near(at(im, 0.5, 0.5), BLUE)
    assert not near(at(im, 0.5, 0.5), RED)
    # Drehen 90: Quelle 320x180 wird 180x320 und in 16:9 eingepasst (schwarze Balken links/rechts)
    im = frame(proj(rotate=90), 1.0, "rot90")
    assert near(at(im, 0.5, 0.2), RED) and near(at(im, 0.5, 0.8), BLUE), (at(im, .5, .2), at(im, .5, .8))
    assert near(at(im, 0.05, 0.5), (0, 0, 0))
    print("OK  Spiegeln, Zuschneiden, Drehen")

    # Keyframes: Zoom 100 -> 300 % zur Bildmitte (Naht Rot|Blau): am Ende ist die gelbe Ecke weg, Mitte bleibt Naht
    kf = [{"t": 0, "zoom": 100, "x": 0, "y": 0, "rot": 0}, {"t": 1, "zoom": 300, "x": 0, "y": 0, "rot": 0}]
    p = proj(keyframes=kf, motion_ease=False)
    start, end = frame(p, 0.1, "kz0"), frame(p, 3.8, "kz1")
    assert near(at(start, 0.02, 0.03), YEL), at(start, .02, .03)
    assert not near(at(end, 0.02, 0.03), YEL), at(end, .02, .03)
    assert near(at(end, 0.25, 0.5), RED) and near(at(end, 0.75, 0.5), BLUE)
    print("OK  Keyframe-Zoom")

    # Schwenk: Zoom 200 %, x von -100 (links) bis +100 (rechts): erst Rot, am Ende Blau im ganzen Bild
    kf = [{"t": 0, "zoom": 200, "x": -100, "y": 0, "rot": 0}, {"t": 1, "zoom": 200, "x": 100, "y": 0, "rot": 0}]
    p = proj(keyframes=kf)
    a, b = frame(p, 0.05, "pan0"), frame(p, 3.9, "pan1")
    assert near(at(a, 0.5, 0.5), RED) or near(at(a, 0.4, 0.5), RED), at(a, .5, .5)
    assert near(at(b, 0.6, 0.5), BLUE), at(b, .6, .5)
    print("OK  Keyframe-Schwenk")

    # Drehung: kleine Winkel rendern, Kombination mit Übergang/Grading nicht kaputt
    p = proj(keyframes=[{"t": 0, "zoom": 120, "x": 0, "y": 0, "rot": -5}, {"t": 1, "zoom": 120, "x": 0, "y": 0, "rot": 5}],
             rotate=180, grade={"brightness": 10})
    frame(p, 2.0, "rot_kf")
    print("OK  Keyframe-Drehung + Transform + Bild")

    # Alle Bewegungs-Presets
    ms = presets.load("motions")
    assert len(ms) >= 8
    for m in ms:
        p = proj(keyframes=m["keyframes"])
        frame(p, 1.5, f"mo_{m['id']}")
    print(f"OK  alle {len(ms)} Bewegungs-Presets rendern")

    # Rückwärtskompatibilität
    f = tmp / "t.cforge"; p.save(str(f))
    d = json.loads(f.read_text(encoding="utf-8"))
    for k in ("rotate", "flip_h", "flip_v", "crop_l", "crop_r", "crop_t", "crop_b", "keyframes", "motion_ease"):
        d["clips"][0].pop(k, None)
    f.write_text(json.dumps(d), encoding="utf-8")
    q = Project.load(str(f)); assert q.clips[0].keyframes == [] and not q.clips[0].has_transform
    print("OK  altes Projekt")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
