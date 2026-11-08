"""Keyframes für Bild-in-Bild und Rückwärts (echtes FFmpeg, Pixelprüfung) + Datenlogik."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, overlaykeys  # noqa: E402
from app.core.project import Clip, IMAGE_MAX, OverlayClip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def solid_video(name, color, dur, size="320x180"):
    f = tmp / name
    sh("-f", "lavfi", "-i", f"color=c={color}:s={size}:r=25:d={dur}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f))
    return f


def solid_image(name, color, size="200x120"):
    f = tmp / name
    sh("-f", "lavfi", "-i", f"color=c={color}:s={size}", "-frames:v", "1", str(f))
    return f


def clip_of(path):
    i = probe(str(path))
    return Clip(str(path), i.duration, has_audio=i.has_audio, width=i.width, height=i.height)


def render(p, name):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    return out


def frame(video, t):
    png = tmp / "f.png"
    sh("-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(png))
    return np.array(Image.open(png).convert("RGB")).astype(int)


def mid(im):
    h, w, _ = im.shape
    return im[h // 2, w // 2]


def near(c, ref, tol=45):
    return all(abs(int(a) - b) <= tol for a, b in zip(c, ref))


def box_of(im, color, tol=60):
    """Begrenzungsrahmen (x0, y0, x1, y1) in Anteilen des Bildes für alle Pixel nahe der Farbe; None wenn keins."""
    m = np.all(np.abs(im - np.array(color)) <= tol, axis=2)
    if not m.any():
        return None
    ys, xs = np.where(m)
    h, w = m.shape
    return xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h


BLUE, RED = (16, 32, 224), (224, 16, 16)


def base():
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [clip_of(solid_video("blue.mp4", "0x1020e0", 4))]
    return p


def red_ov(**kw):
    return OverlayClip(str(solid_image("o.png", "0xe01010")), IMAGE_MAX, 0.0, 4.0, start=0.0, is_image=True, **kw)


def main() -> int:
    # --- Datenlogik ---
    o = OverlayClip("x.png", 5, 0, 4, is_image=True, x_pct=75, y_pct=25, size_pct=30)
    assert not overlaykeys.active(o)
    junk = overlaykeys.clean([5, {"t": 2, "x": "abc", "size": 500, "opacity": -5}, {"t": -1}, {"t": 0.5, "x": 1e9}], o)
    assert [k["t"] for k in junk] == [0.0, 0.5, 1.0] and junk[2]["size"] == 100.0 and junk[2]["opacity"] == 0.0
    assert junk[2]["x"] == 75.0 and junk[1]["x"] == 150.0, junk
    assert len(overlaykeys.clean([{"t": i / 40} for i in range(40)], o)) == overlaykeys.MAX_KEYS
    same = overlaykeys.clean([{"t": 0.5}, {"t": 0.5}, {"t": 0.5}], o)
    assert len(same) == 3 and same[0]["t"] < same[1]["t"] < same[2]["t"]
    i0 = overlaykeys.add_key(o, 0.5)
    assert len(o.keys) == 3 and o.keys[i0]["t"] == 0.5 and o.keys[i0]["x"] == 75.0
    assert overlaykeys.add_key(o, 0.51) == i0 and len(o.keys) == 3, "Punkt in der Nähe wird wiederverwendet"
    assert overlaykeys.set_key(o, 1, x=10, opacity=50, t=0.4)
    assert o.keys[1]["x"] == 10 and o.keys[1]["t"] == 0.4
    v = overlaykeys.value_at(o.keys, 0.2, ease=False)
    assert abs(v["x"] - (75 + (10 - 75) * 0.5)) < 1e-6, v
    assert overlaykeys.remove_key(o, 1) and len(o.keys) == 2
    assert overlaykeys.remove_key(o, 0) and o.keys == [], "ein einzelner Punkt wird verworfen"
    assert not overlaykeys.remove_key(o, 5)
    for name in overlaykeys.PRESETS:
        o.keys = []
        assert overlaykeys.apply_preset(name, o) and overlaykeys.active(o), name
        assert all(overlaykeys.LIMITS[f][0] <= k[f] <= overlaykeys.LIMITS[f][1] for k in o.keys for f in overlaykeys.FIELDS)
    assert not overlaykeys.apply_preset("gibtsnicht", o)
    o.cell = [0, 0, 50, 50]
    assert not overlaykeys.active(o), "Split-Felder ignorieren Keyframes"
    print("OK  Datenlogik (bereinigen, einfügen, löschen, Vorlagen)")

    # --- Position: von links oben nach rechts unten ---
    p = base()
    ov = red_ov(x_pct=20, y_pct=25, size_pct=20)
    ov.keys = [{"t": 0, "x": 20, "y": 25, "size": 20, "opacity": 100}, {"t": 1, "x": 80, "y": 75, "size": 20, "opacity": 100}]
    ov.anim_ease = False
    p.overlays = [ov]
    out = render(p, "k_pos")
    b0 = box_of(frame(out, 0.2), RED); b1 = box_of(frame(out, 3.6), RED)
    assert b0 and b1, (b0, b1)
    c0 = ((b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2); c1 = ((b1[0] + b1[2]) / 2, (b1[1] + b1[3]) / 2)
    assert c0[0] < 0.3 and c0[1] < 0.35, c0
    assert c1[0] > 0.7 and c1[1] > 0.65, c1
    mb = box_of(frame(out, 2.0), RED); cm = ((mb[0] + mb[2]) / 2, (mb[1] + mb[3]) / 2)
    assert 0.4 < cm[0] < 0.6 and 0.4 < cm[1] < 0.6, cm
    print("OK  Keyframes Position", [round(v, 2) for v in c0], [round(v, 2) for v in cm], [round(v, 2) for v in c1])

    # --- Größe: 20 % -> 60 % Breite ---
    p = base()
    ov = red_ov(x_pct=50, y_pct=50, size_pct=20)
    ov.keys = [{"t": 0, "x": 50, "y": 50, "size": 20, "opacity": 100}, {"t": 1, "x": 50, "y": 50, "size": 60, "opacity": 100}]
    ov.anim_ease = False
    p.overlays = [ov]
    out = render(p, "k_size")
    w0 = box_of(frame(out, 0.2), RED); w1 = box_of(frame(out, 3.7), RED)
    a0 = w0[2] - w0[0]; a1 = w1[2] - w1[0]
    assert 0.17 < a0 < 0.3 and 0.5 < a1 < 0.62, (a0, a1)
    print("OK  Keyframes Größe", round(a0, 2), "->", round(a1, 2))

    # --- Deckkraft: 100 % -> 0 % ---
    p = base()
    ov = red_ov(x_pct=50, y_pct=50, size_pct=50)
    ov.keys = [{"t": 0, "x": 50, "y": 50, "size": 50, "opacity": 100}, {"t": 1, "x": 50, "y": 50, "size": 50, "opacity": 0}]
    ov.anim_ease = False
    p.overlays = [ov]
    out = render(p, "k_op")
    r0 = mid(frame(out, 0.1))[0]; rm = mid(frame(out, 2.0))[0]; r1 = mid(frame(out, 3.8))[0]
    assert r0 > 190 and 90 < rm < 170 and r1 < 60, (r0, rm, r1)
    print("OK  Keyframes Deckkraft", r0, rm, r1)

    # --- alles zusammen, mit Rahmen, Blenden, Standbild und Video, ohne Absturz ---
    p = base()
    vid = clip_of(solid_video("g.mp4", "0x20c020", 3))
    ov = OverlayClip(str(vid.path), vid.duration, 0.0, 3.0, start=0.5, border=True, fade_in=0.3, fade_out=0.3, size_pct=30)
    overlaykeys.apply_preset("zoom_up", ov)
    ov2 = red_ov(x_pct=30, y_pct=30, size_pct=25, border=True)
    overlaykeys.apply_preset("swing", ov2)
    p.overlays = [ov, ov2]
    out = render(p, "k_all")
    assert abs(probe(str(out)).duration - 4.0) < 0.3
    print("OK  Keyframes mit Rahmen, Blenden, Video und Bild")

    # --- ohne Keyframes unverändert, alter Pfad ---
    p = base()
    p.overlays = [red_ov(x_pct=75, y_pct=25, size_pct=30)]
    cmd, _, _ = exporter.build_command(p, str(tmp / "nokeys.mp4"), draft=True)
    assert "geq" not in " ".join(cmd) and "eval=frame" not in " ".join(cmd)
    print("OK  ohne Keyframes unverändert")

    # --- Rückwärts: Video mit rot -> grün, rückwärts erst grün dann rot ---
    rg = tmp / "rg.mp4"
    sh("-f", "lavfi", "-i", "color=c=0xe01010:s=320x180:r=25:d=2", "-f", "lavfi", "-i", "color=c=0x20c020:s=320x180:r=25:d=2",
       "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(rg))
    p = base()
    ov = OverlayClip(str(rg), 4.0, 0.0, 4.0, start=0.0, x_pct=50, y_pct=50, size_pct=60)
    p.overlays = [ov]
    f_norm = render(p, "rev0")
    assert near(mid(frame(f_norm, 0.5)), RED) and near(mid(frame(f_norm, 3.5)), (32, 192, 32))
    ov.reverse = True
    f_rev = render(p, "rev1")
    assert near(mid(frame(f_rev, 0.5)), (32, 192, 32)) and near(mid(frame(f_rev, 3.5)), RED), \
        (mid(frame(f_rev, 0.5)), mid(frame(f_rev, 3.5)))
    ov.reverse = True; ov.out_pt = 4.0
    ov.keys = [{"t": 0, "x": 40, "y": 50, "size": 60, "opacity": 100}, {"t": 1, "x": 60, "y": 50, "size": 60, "opacity": 100}]
    render(p, "rev2")
    print("OK  Rückwärts (auch zusammen mit Keyframes)")

    # --- Ton eines rückwärts laufenden Blocks wird ebenfalls umgedreht ---
    wa = tmp / "wa.mp4"
    sh("-f", "lavfi", "-i", "color=c=0x20c020:s=320x180:r=25:d=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(wa))
    pa = base()
    oa = OverlayClip(str(wa), 2.0, 0.0, 2.0, start=0.0, sound=True)
    pa.overlays = [oa]
    c1 = " ".join(exporter.build_command(pa, str(tmp / "a1.mp4"), draft=True)[0])
    oa.reverse = True
    c2 = " ".join(exporter.build_command(pa, str(tmp / "a2.mp4"), draft=True)[0])
    assert "areverse" not in c1 and "areverse" in c2
    render(pa, "a_rev")
    print("OK  Ton läuft rückwärts mit")

    # --- Fehlermeldung bei zu langem Rückwärts-Block ---
    ov.keys = []; ov.out_pt = 120.0; ov.duration = 120.0
    try:
        exporter.build_command(p, str(tmp / "x.mp4"), draft=True)
        raise AssertionError("zu langer Rückwärts-Block hätte abbrechen müssen")
    except exporter.ExportError as e:
        assert "Rückwärts" in str(e)
    print("OK  zu langes Rückwärts meldet Fehler")

    # --- Speichern/Laden, altes Projekt ---
    p = base()
    ov = red_ov(x_pct=20, y_pct=25, size_pct=20)
    overlaykeys.apply_preset("in_left", ov); ov.reverse = False; ov.anim_ease = False
    p.overlays = [ov]
    f = tmp / "k.cforge"; p.save(str(f))
    q = Project.load(str(f))
    assert q.overlays[0].keys == ov.keys and q.overlays[0].anim_ease is False
    d = json.loads(f.read_text(encoding="utf-8"))
    for key in ("keys", "anim_ease", "reverse"):
        d["overlays"][0].pop(key, None)
    f.write_text(json.dumps(d), encoding="utf-8")
    q = Project.load(str(f))
    assert q.overlays[0].keys == [] and q.overlays[0].anim_ease is True and q.overlays[0].reverse is False
    print("OK  Speichern/Laden, altes Projekt")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
