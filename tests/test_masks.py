"""Masken-Effekte (1.3.1) mit echtem FFmpeg: Form, Weiche Kante, Umkehren, Zeitfenster, Tracking-Pfad, Fehlertoleranz."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import effects as fx, exporter  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def make_source(name, dur=3.0, stripes=False):
    f = tmp / name
    if stripes:      # feine schwarz-weiße Schachbrett-Streifen (16 Pixel, im Entwurf 4) – zeigt Weichzeichnen und Mosaik
        src = ["-f", "lavfi", "-i", f"color=c=gray:s=1920x1080:r=25:d={dur}",
               "-vf", "format=yuv420p,geq=lum='if(mod(floor(X/16)+floor(Y/16),2),235,16)':cb=128:cr=128"]
    else:            # mittelgrau
        src = ["-f", "lavfi", "-i", f"color=c=0x909090:s=1920x1080:r=25:d={dur}"]
    sh(*src, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f))
    return f


def render(src, blocks, name="m", dur=3.0):
    i = probe(str(src))
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(src), i.duration, has_audio=False, width=i.width, height=i.height)]
    p.effects = blocks
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    return out


def frame(video, t):
    png = tmp / "f.png"
    sh("-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(png))
    return np.array(Image.open(png).convert("L")).astype(float)


def at(im, fx_, fy_):
    h, w = im.shape
    return im[int(h * fy_), int(w * fx_)]


def patch(im, cx, cy, r=0.04):
    h, w = im.shape
    return im[int(h * (cy - r)):int(h * (cy + r)), int(w * (cx - r)):int(w * (cx + r))]


def blk(id_, mask=None, intensity=100, **kw):
    b = {"id": id_, "intensity": intensity, **kw}
    if mask is not None:
        b["mask"] = mask
    return b


def main() -> int:
    # --- Modell und Formel
    assert set(fx.REGISTRY) >= {"mask_blur", "mask_mosaic", "mask_dim", "mask_black"}
    p = fx.mask_params({"x": "70", "w": 9999, "shape": "stern", "feather": -5, "track": [[2, 10, 10], [1, 20, 200], ["x"], [0, 5, 5]]})
    assert p["x"] == 70.0 and p["w"] == 200.0 and p["shape"] == "ellipse" and p["feather"] == 0.0
    assert [q[0] for q in p["track"]] == [0.0, 1.0, 2.0] and p["track"][1][2] == 100.0, p["track"]
    assert fx.mask_params(None)["w"] == 30.0 and fx.mask_params("quatsch")["h"] == 30.0
    many = fx.mask_params({"track": [[i * 0.1, i % 100, 50] for i in range(500)]})["track"]
    assert len(many) == fx.MASK_TRACK_MAX
    print("OK  Maskenwerte werden bereinigt")

    plain = make_source("plain.mp4")
    base = frame(plain, 1.0)
    base_v = at(base, 0.5, 0.5)

    # --- Schwärzen: Ellipse innen schwarz, Ecke unberührt; Umkehren dreht das um
    out = render(plain, [blk("mask_black", {"shape": "ellipse", "x": 50, "y": 50, "w": 30, "h": 40, "feather": 0})])
    im = frame(out, 1.0)
    assert at(im, 0.5, 0.5) < 30 and abs(at(im, 0.05, 0.05) - base_v) < 6 and abs(at(im, 0.95, 0.9) - base_v) < 6
    assert abs(at(im, 0.5 + 0.17, 0.5) - base_v) < 8, "knapp außerhalb der Ellipse (w=30 %) bleibt unberührt"
    assert at(im, 0.5 + 0.12, 0.5) < 30, "knapp innerhalb ist schwarz"
    print("OK  Maske schwärzen (Ellipse)")
    out = render(plain, [blk("mask_black", {"shape": "ellipse", "x": 50, "y": 50, "w": 30, "h": 40, "feather": 0, "invert": True})])
    im = frame(out, 1.0)
    assert abs(at(im, 0.5, 0.5) - base_v) < 6 and at(im, 0.05, 0.05) < 30 and at(im, 0.95, 0.9) < 30
    print("OK  Umkehren")

    # --- Rechteck: die Ecke der Form ist (anders als bei der Ellipse) betroffen
    out = render(plain, [blk("mask_black", {"shape": "rect", "x": 50, "y": 50, "w": 40, "h": 40, "feather": 0})])
    im = frame(out, 1.0)
    assert at(im, 0.5 - 0.18, 0.5 - 0.18) < 30 and abs(at(im, 0.5 - 0.23, 0.5 - 0.23) - base_v) < 6
    print("OK  Rechteck")

    # --- Weiche Kante: scharf = kaum Zwischenwerte, weich = Verlauf
    def edge_values(feather):
        o = render(plain, [blk("mask_black", {"shape": "rect", "x": 50, "y": 50, "w": 40, "h": 60, "feather": feather})], f"feather{feather}")
        row = frame(o, 1.0)[int(270 * 0.5), :]
        mid = row[(row > 40) & (row < base_v - 40)]
        return len(mid)
    hard, soft = edge_values(0), edge_values(100)
    assert soft > hard + 20, (hard, soft)
    print("OK  Weiche Kante (hart", hard, "Pixel Übergang, weich", soft, ")")

    # --- Dimmen: Innen bleibt, außen dunkel
    out = render(plain, [blk("mask_dim", {"x": 50, "y": 50, "w": 30, "h": 30, "feather": 10}, 80)])
    im = frame(out, 1.0)
    assert abs(at(im, 0.5, 0.5) - base_v) < 8 and at(im, 0.05, 0.05) < base_v - 40, (at(im, 0.5, 0.5), at(im, 0.05, 0.05))
    print("OK  Hervorheben (Rest abdunkeln)")

    # --- Weichzeichnen und Mosaik auf feinem Muster: innen weniger Kontrast als außen
    pat = make_source("stripes.mp4", stripes=True)
    ref = frame(pat, 1.0)
    assert patch(ref, 0.5, 0.5).std() > 80
    for kind in ("mask_blur", "mask_mosaic"):
        out = render(pat, [blk(kind, {"x": 50, "y": 50, "w": 30, "h": 40, "feather": 0}, 80)], kind)
        im = frame(out, 1.0)
        inside, outside = patch(im, 0.5, 0.5).std(), patch(im, 0.1, 0.1).std()
        assert inside < 45 and outside > 80, (kind, inside, outside)
    print("OK  Weichzeichnen und Verpixeln")

    # --- Zeitfenster: nur von 1 s bis 2 s
    out = render(plain, [blk("mask_black", {"x": 50, "y": 50, "w": 30, "h": 30}, start=1.0, end=2.0)])
    assert abs(at(frame(out, 0.4), 0.5, 0.5) - base_v) < 6 and at(frame(out, 1.5), 0.5, 0.5) < 30 and abs(at(frame(out, 2.6), 0.5, 0.5) - base_v) < 6
    print("OK  Zeitfenster")

    # --- Verfolgter Pfad: Maske wandert von links nach rechts; Zeiten zählen ab Blockanfang
    track = [[0.0, 20.0, 50.0], [2.0, 80.0, 50.0]]
    out = render(plain, [blk("mask_black", {"x": 50, "y": 50, "w": 10, "h": 20, "feather": 0, "track": track}, start=0.5, end=2.9)], "track")
    for t, cx in ((0.5, 0.20), (1.5, 0.50), (2.5, 0.80)):
        im = frame(out, t)
        assert at(im, cx, 0.5) < 30, (t, cx, at(im, cx, 0.5))
        far = 0.8 if cx < 0.6 else 0.2
        assert abs(at(im, far, 0.5) - base_v) < 6, (t, far)
    print("OK  Tracking-Pfad (Maske wandert mit)")

    # --- 60 Pfadpunkte, mehrere Maskenblöcke gleichzeitig, kaputte Werte
    pts = [[i * 0.04, 10 + i * 1.2, 50 + (i % 5)] for i in range(60)]
    out = render(plain, [blk("mask_blur", {"track": pts}), blk("mask_black", {"x": 10, "y": 10, "w": 8, "h": 8}),
                         blk("mask_mosaic", {"x": "kaputt", "track": [["a", "b"], None, [1, 2]]}), blk("mask_dim", None)], "many")
    assert at(frame(out, 1.0), 0.1, 0.1) < 30
    print("OK  viele Blöcke, 60 Pfadpunkte, kaputte Maskenwerte")

    # --- Speichern/Laden bewahrt die Maske
    pr = Project(format_id="shorts", effects=[blk("mask_blur", {"track": track, "shape": "rect"})])
    back = Project.from_json(pr.to_json())
    assert back.effects[0]["mask"]["track"] == track and back.effects[0]["mask"]["shape"] == "rect"
    print("OK  Speichern/Laden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
