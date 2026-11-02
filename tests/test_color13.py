"""1.3: Farbräder, Kurven, LUT (auch mit Sonderzeichen im Pfad), Chroma-Key – alles mit echtem FFmpeg und Pixelprüfung."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, grade  # noqa: E402
from app.core.project import Clip, OverlayClip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def solid_video(name, color, dur=1, size="320x180"):
    f = tmp / name
    sh("-f", "lavfi", "-i", f"color=c={color}:s={size}:r=25:d={dur}", "-c:v", "libx264", "-pix_fmt", "yuv444p", str(f))
    return f


def gray(v):
    return f"0x{v:02x}{v:02x}{v:02x}"


def px_of(video, fx=0.5, fy=0.5, t=0.4):
    png = tmp / "f.png"
    sh("-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(png))
    im = np.array(Image.open(png).convert("RGB"))
    h, w, _ = im.shape
    return tuple(int(v) for v in im[int(h * fy), int(w * fx)])


def graded(src, g, name="g.png"):
    """Wendet die Korrektur über denselben Graphen wie der Export an und liest ein Pixel."""
    out = tmp / name
    graph = grade.apply_label("0:v", "o", g)
    r = subprocess.run([ff, "-v", "error", "-y", "-i", str(src), "-filter_complex", graph, "-map", "[o]",
                        "-frames:v", "1", str(out)], capture_output=True, text=True)
    assert r.returncode == 0 and not r.stderr.strip(), (graph, r.stderr[-400:])
    im = np.array(Image.open(out).convert("RGB"))
    return tuple(int(v) for v in im[10, 10])


def near(a, b, tol=10):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def write_cube(path, fn, n=17):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'TITLE "test"\nLUT_3D_SIZE {n}\n')
        for b in range(n):
            for g in range(n):
                for r in range(n):
                    R, G, B = fn(r / (n - 1), g / (n - 1), b / (n - 1))
                    f.write(f"{R:.5f} {G:.5f} {B:.5f}\n")


def write_cube_1d(path, fn, n=33):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"LUT_1D_SIZE {n}\n")
        for i in range(n):
            x = i / (n - 1)
            f.write(f"{fn(x):.5f} {fn(x):.5f} {fn(x):.5f}\n")


def main() -> int:
    # ---- Bereinigung / Modell
    assert grade.is_neutral({"curves": {"m": [[0, 0], [1, 1]]}}), "Diagonale = neutral"
    assert grade.is_neutral({"lut": "", "lut_mix": 40}) and grade.is_neutral({"lift_r": 0})
    c = grade.clean({"curves": {"m": [[0.5, 0.7], [0.1, 0.1], ["x", 1], [0.5, 0.2]], "q": [[0, 0]]},
                     "lut": "a.cube", "lut_mix": 250, "mid_r": "30", "foo": 1})
    assert c["curves"] == {"m": [[0.0, 0.0], [0.1, 0.1], [0.5, 0.7], [1.0, 1.0]]}, c
    assert c["mid_r"] == 30.0 and "foo" not in c and "lut_mix" not in c and c["lut"] == "a.cube"
    assert grade.clean({"lut": "a.cube", "lut_mix": 0})["lut_mix"] == 1.0
    pts = grade.normalize_points([[i / 30, 0.5] for i in range(31)])
    assert len(pts) <= grade.CURVE_MAX_POINTS and pts[0][0] == 0.0 and pts[-1][0] == 1.0
    print("OK  Bereinigung von Kurven, LUT und Rädern")

    # ---- Farbräder: jede Zone wirkt in ihrem Helligkeitsbereich auf den richtigen Kanal
    for zone, level in (("lift", 0x18), ("mid", 0x40), ("gain", 0x90)):
        src = solid_video(f"{zone}.mp4", gray(level))
        base = graded(src, {})
        out = graded(src, {f"{zone}_r": 100, f"{zone}_g": -50, f"{zone}_b": -50})
        assert out[0] > base[0] + 25 and out[1] < base[1] and out[2] < base[2], (zone, base, out)
        out = graded(src, {f"{zone}_b": 100})
        assert out[2] > base[2] + 25 and abs(out[0] - base[0]) <= 3, (zone, base, out)
    print("OK  Farbräder (Schatten, Mitten, Lichter)")
    allw = {k: 100 for k in grade.WHEEL_KEYS}
    allw.update({k: -100 for k in grade.WHEEL_KEYS[::2]})
    graded(solid_video("w.mp4", gray(0x80)), allw)
    print("OK  alle Räder gleichzeitig am Anschlag")

    # ---- Kurven
    g80 = solid_video("g80.mp4", gray(0x80))
    assert near(graded(g80, {"curves": {"m": [[0, 0], [0.5, 0.8], [1, 1]]}}), (204, 204, 204), 8)
    assert near(graded(g80, {"curves": {"m": [[0, 1], [1, 0]]}}), (127, 127, 127), 8)         # invertiert
    r, g, b = graded(g80, {"curves": {"r": [[0, 0], [0.5, 0.75], [1, 1]]}})
    assert r > 170 and abs(g - 128) <= 4 and abs(b - 128) <= 4, (r, g, b)
    r, g, b = graded(g80, {"curves": {"b": [[0, 0.2], [1, 1]]}})                               # Schwarzwert heben
    assert b > 150 and abs(r - 128) <= 4, (r, g, b)
    graded(g80, {"curves": {ch: [[i / 11, min(1.0, i / 11 + 0.05 * (i % 2))] for i in range(12)] for ch in "mrgb"}})
    print("OK  Kurven (Master, einzelne Kanäle, 12 Punkte)")

    # ---- LUT (rot halbieren) mit harmlosen und schwierigen Pfaden
    for name in ("lut.cube", "mein lut's [a],b;c.cube", "ü ö x.cube"):
        p = tmp / name
        write_cube(p, lambda r, g, b: (r * 0.5, g, b))
        assert near(graded(g80, {"lut": str(p)}), (64, 128, 128), 8), name
        assert near(graded(g80, {"lut": str(p), "lut_mix": 50}), (96, 128, 128), 8), name
        # zusammen mit Korrekturen davor und danach (Schärfe liegt hinter der LUT)
        graded(g80, {"lut": str(p), "lut_mix": 30, "saturation": 10, "sharpen": 20, "curves": {"m": [[0, 0], [0.5, 0.6], [1, 1]]}})
    print("OK  LUT (voll, gemischt, Sonderzeichen im Pfad)")
    p1 = tmp / "eins d.cube"
    write_cube_1d(p1, lambda x: 1 - x)
    assert grade.lut_kind(str(p1)) == "lut1d" and grade.lut_kind(str(tmp / "lut.cube")) == "lut3d"
    assert near(graded(g80, {"lut": str(p1)}), (127, 127, 127), 8)
    print("OK  1D-LUT")
    # fehlende LUT-Datei darf nichts kaputt machen
    assert near(graded(g80, {"lut": str(tmp / "weg.cube")}), (128, 128, 128), 4)
    print("OK  fehlende LUT wird übersprungen")

    # ---- Export: neue Felder pro Clip, Speichern/Laden, alte Projekte
    i = probe(str(g80))
    cl = Clip(str(g80), i.duration, has_audio=False, width=i.width, height=i.height,
              grade={"lut": str(tmp / "lut.cube"), "lut_mix": 50, "mid_r": 40, "curves": {"m": [[0, 0], [0.5, 0.6], [1, 1]]}})
    proj = Project(format_id="youtube_16_9", export_id="youtube_1080p", clips=[cl, Clip(str(g80), i.duration, has_audio=False, width=i.width, height=i.height)])
    out = tmp / "ex.mp4"
    cmd, total, _ = exporter.build_command(proj, str(out), draft=True)
    exporter.run(cmd, total)
    assert abs(probe(str(out)).duration - total) < 0.3
    back = Project.from_json(proj.to_json())
    assert back.clips[0].grade == cl.grade and back.clips[1].grade == {}
    assert back.missing_paths() == []
    (tmp / "neu").mkdir(exist_ok=True)
    (tmp / "lut.cube").rename(tmp / "neu" / "lut.cube")
    assert back.missing_paths() == [str(tmp / "lut.cube")]
    n, still = back.relink(str(tmp / "neu"))
    assert n == 1 and not still and back.clips[0].grade["lut"] == str(tmp / "neu" / "lut.cube"), back.clips[0].grade
    assert back.missing_paths() == []
    print("OK  Export, Speichern/Laden, fehlende LUT melden")
    old = {"format_id": "shorts", "clips": [{"path": str(g80), "duration": 1.0, "grade": {"brightness": 10}}]}
    (tmp / "alt.cforge").write_text(json.dumps(old), encoding="utf-8")
    assert Project.load(str(tmp / "alt.cforge")).clips[0].grade == {"brightness": 10}
    print("OK  altes Projekt lädt")

    # ---- Vorher/Nachher-Bild mit LUT-Mischung
    png = grade.render_preview(str(g80), 0.3, {"lut": str(tmp / "ü ö x.cube"), "lut_mix": 40, "lift_g": 20})
    assert Path(png).stat().st_size > 500
    print("OK  Vorher/Nachher-Bild mit LUT")

    # ---- Chroma-Key: grüner Hintergrund mit rotem Quadrat über blauem Hauptvideo
    blue = solid_video("bg.mp4", "0x1020e0", 2)
    ovp = tmp / "green.mp4"
    sh("-f", "lavfi", "-i", "color=c=0x00ff00:s=320x180:r=25:d=2", "-vf", "drawbox=x=110:y=50:w=100:h=80:color=0xff2020:t=fill",
       "-c:v", "libx264", "-pix_fmt", "yuv444p", str(ovp))
    bi = probe(str(blue))
    oi = probe(str(ovp))

    def key_project(**kw):
        p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
        p.clips = [Clip(str(blue), bi.duration, has_audio=False, width=bi.width, height=bi.height)]
        p.overlays = [OverlayClip(str(ovp), oi.duration, 0.0, oi.duration, start=0.0, x_pct=50, y_pct=50, size_pct=100, **kw)]
        return p

    def render(p, name):
        o = tmp / f"{name}.mp4"
        cmd, total, _ = exporter.build_command(p, str(o), draft=True)
        exporter.run(cmd, total)
        return o

    o = render(key_project(), "nokey")
    assert near(px_of(o, 0.05, 0.1), (0, 255, 0), 40), px_of(o, 0.05, 0.1)
    o = render(key_project(key_color="#00ff00"), "key")
    corner, centre = px_of(o, 0.05, 0.1), px_of(o, 0.5, 0.5)
    assert near(corner, (16, 32, 224), 45), ("Hintergrund muss durchscheinen", corner)
    assert near(centre, (255, 32, 32), 60), ("Rotes Quadrat bleibt", centre)
    o = render(key_project(key_color="00FF00", key_spill=False, key_similarity=60, key_blend=0), "key2")
    assert near(px_of(o, 0.05, 0.1), (16, 32, 224), 45)
    o = render(key_project(key_color="#0000ff", key_spill=True), "key_blue")           # falsche Farbe: Grün bleibt stehen
    assert near(px_of(o, 0.05, 0.1), (0, 255, 0), 60)
    o = render(key_project(key_color="kaputt"), "key_bad")
    assert near(px_of(o, 0.05, 0.1), (0, 255, 0), 40), "ungültige Farbe = aus"
    assert exporter.chromakey_filters(OverlayClip("x", 1.0)) == ""
    print("OK  Chroma-Key (Hintergrund wird transparent, Motiv bleibt, falsche/ungültige Farbe)")

    # Standbild-Overlay (Bild mit grünem Hintergrund) + Deckkraft + Blenden
    imgp = tmp / "gimg.png"
    sh("-f", "lavfi", "-i", "color=c=0x00ff00:s=200x120", "-vf", "drawbox=x=60:y=30:w=80:h=60:color=0xffff00:t=fill", "-frames:v", "1", str(imgp))
    p = key_project(key_color="#00ff00", opacity=100, fade_in=0.2)
    p.overlays[0] = OverlayClip(str(imgp), 5.0, 0.0, 2.0, is_image=True, x_pct=50, y_pct=50, size_pct=100,
                                key_color="#00ff00", fade_in=0.2)
    o = render(p, "key_img")
    assert near(px_of(o, 0.05, 0.1, t=1.0), (16, 32, 224), 45), px_of(o, 0.05, 0.1, t=1.0)
    print("OK  Chroma-Key mit Standbild")

    d = json.loads(key_project(key_color="#00ff00").to_json())
    d["overlays"][0].pop("key_color")
    assert Project.from_json(json.dumps(d)).overlays[0].key_color == ""
    print("OK  altes Projekt ohne Chroma-Key-Felder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
