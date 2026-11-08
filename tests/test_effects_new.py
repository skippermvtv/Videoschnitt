"""Neue Effekte aus 1.4.8: laufen bei Intensität 0 / 50 / 100 durch (echtes FFmpeg) und wirken im Pixelvergleich."""
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import effects as fx  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
W, H, FPS = 240, 90, 25
ctx = fx.Ctx(W, H, FPS)
NEW = ["tilt_shift", "zoom_blur", "stop_motion", "light_leak", "pencil", "thermal", "keep_red", "keep_green",
       "keep_blue", "strobe", "double_exposure", "xray"]


def frames(src: str, eid: str, k: int, dur: float = 2.0, window=None) -> np.ndarray:
    """Rendert Quelle + Effekt und liefert alle Bilder als Array (n, H, W, 3)."""
    item = {"id": eid, "intensity": k}
    if window:
        item["start"], item["end"] = window
    graph = ";".join([f"{src}[src]"] + fx.build_graph([item], "src", "out", ctx) + ["[out]format=rgb24[fin]"])
    cmd = [ff, "-v", "error", "-y", "-filter_complex", graph, "-map", "[fin]", "-t", str(dur), "-r", str(FPS),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    r = subprocess.run(cmd, capture_output=True)
    assert r.returncode == 0 and not r.stderr.strip(), (eid, k, r.stderr.decode()[:500])
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    n = a.size // (W * H * 3)
    assert n >= int(dur * FPS) - 2, (eid, n)
    return a[: n * W * H * 3].reshape(n, H, W, 3).astype(int)


def solid(color: str) -> str:
    return f"color=c={color}:s={W}x{H}:r={FPS}:d=3"


def three_fields() -> str:
    cw = W // 3
    return (f"color=c=0xe01010:s={cw}x{H}:r={FPS}:d=3[fr];color=c=0x10c010:s={cw}x{H}:r={FPS}:d=3[fg];"
            f"color=c=0x1030e0:s={cw}x{H}:r={FPS}:d=3[fb];[fr][fg][fb]hstack=inputs=3")


def px(im, fx_, fy):
    return im[int(H * fy), int(W * fx_)]


def gray(c, tol=28):
    return max(c) - min(c) <= tol


def main() -> int:
    # 1) alle neuen Effekte laufen bei 0, 50, 100
    for eid in NEW:
        assert eid in fx.REGISTRY, eid
        for k in (0, 50, 100):
            frames(solid("0x808080"), eid, k, dur=0.5)
        print("OK ", eid)

    # 2) Nur Farbe behalten
    src = three_fields()
    for eid, idx in (("keep_red", 0), ("keep_green", 1), ("keep_blue", 2)):
        im = frames(src, eid, 60, dur=0.4)[3]
        for j in range(3):
            c = px(im, (j + 0.5) / 3, 0.5)
            if j == idx:
                assert not gray(c, 60), (eid, j, c)
            else:
                assert gray(c), (eid, j, c)
    print("OK  Nur Rot/Grün/Blau behalten (Feld bleibt farbig, die anderen werden grau)")

    # 3) Strobe: zu manchen Zeiten schwarz, sonst Bild
    im = frames(solid("0xe01010"), "strobe", 50, dur=1.0)         # 5 Blitze pro Sekunde, schwarz im ersten Teil jeder Periode
    means = im.reshape(len(im), -1).mean(axis=1)
    assert (means < 8).sum() >= 8 and (means > 40).sum() >= 8, means.round(0)
    print("OK  Strobe (", int((means < 8).sum()), "schwarze von", len(means), "Bildern )")

    # 4) Stop-Motion: viel weniger verschiedene Bilder als die Quelle
    moving = f"nullsrc=s={W}x{H}:r={FPS}:d=3,geq=lum='128+100*sin(T*12)':cb=128:cr=128"
    src_frames = frames(moving, "stop_motion", 0, dur=2.0)         # Stärke 0: ca. 18 Bilder/s
    hard = frames(moving, "stop_motion", 100, dur=2.0)
    def changes(a):
        return int(sum(np.abs(a[i + 1] - a[i]).max() > 2 for i in range(len(a) - 1)))
    c_soft, c_hard = changes(src_frames), changes(hard)
    assert c_hard < 14 and c_hard < c_soft, (c_soft, c_hard)
    print("OK  Stop-Motion (Bildwechsel", c_soft, "->", c_hard, "in 2 s)")

    # 5) Zoom-Unschärfe: schärfste Kanten werden weicher
    detail = f"testsrc2=size={W}x{H}:rate={FPS}:duration=3"
    def sharp(a):
        g = a.mean(axis=3)
        return float((np.diff(g, axis=2) ** 2).mean())       # Energie der Kanten: sinkt, wenn Kanten verschmieren
    base = frames(detail, "stop_motion", 0, dur=0.4)[:1]            # fast unverändert (Bilder wiederholt)
    zb = frames(detail, "zoom_blur", 100, dur=0.4)[:1]
    assert sharp(zb) < sharp(base) * 0.85, (sharp(base), sharp(zb))
    print("OK  Zoom-Unschärfe (Schärfe", round(sharp(base)), "->", round(sharp(zb)), ")")

    # 6) Tilt-Shift: Mitte scharf, Rand unscharf
    check = f"nullsrc=s={W}x{H}:r={FPS}:d=3,geq=lum='255*mod(floor(X/3)+floor(Y/3),2)':cb=128:cr=128"
    im = frames(check, "tilt_shift", 100, dur=0.4)[2]
    g = im.mean(axis=2)
    v_mid, v_top = g[int(H * 0.42):int(H * 0.58)].std(), g[:int(H * 0.15)].std()
    assert v_mid > 3 * v_top and v_mid > 60, (v_mid, v_top)
    print("OK  Tilt-Shift (Streuung Mitte", round(v_mid), "oben", round(v_top), ")")

    # 7) Lichtleck: warmer Schein in der Mitte (t = 0), Rand bleibt grau
    im = frames(solid("0x404040"), "light_leak", 100, dur=0.4)[0]
    cen, edge = px(im, 0.5, 0.2), px(im, 0.02, 0.5)
    assert cen[0] - cen[2] > 40 and cen[0] > edge[0] + 40, (cen, edge)
    print("OK  Lichtleck (Mitte", tuple(cen), "Rand", tuple(edge), ")")

    # 8) Bleistiftskizze: Fläche wird weiß, Farben werden grau
    im = frames(three_fields(), "pencil", 60, dur=0.4)[2]
    for j in range(3):
        c = px(im, (j + 0.5) / 3, 0.5)
        assert gray(c, 10) and min(c) > 225, c
    print("OK  Bleistiftskizze")

    # 9) Wärmebild: graue Fläche bekommt Farbe
    im = frames(solid("0x808080"), "thermal", 100, dur=0.4)[2]
    c = px(im, 0.5, 0.5)
    assert not gray(c, 40), c
    print("OK  Wärmebild", tuple(c))

    # 10) Doppelbelichtung: gespiegeltes Bild erscheint auf der schwarzen Seite
    half = f"color=c=white:s={W // 2}x{H}:r={FPS}:d=3[wl];color=c=black:s={W // 2}x{H}:r={FPS}:d=3[bl];[wl][bl]hstack"
    im = frames(half, "double_exposure", 80, dur=0.4)[2]
    assert px(im, 0.75, 0.5)[0] > 60 and px(im, 0.25, 0.5)[0] > 200, (px(im, 0.75, 0.5), px(im, 0.25, 0.5))
    print("OK  Doppelbelichtung")

    # 11) Röntgen: Hell wird dunkel, Dunkel wird hell, bläulicher Ton
    both = f"color=c=white:s={W // 2}x{H}:r={FPS}:d=3[wl];color=c=0x303030:s={W // 2}x{H}:r={FPS}:d=3[bl];[wl][bl]hstack"
    im = frames(both, "xray", 100, dur=0.4)[2]
    a_, b_ = px(im, 0.25, 0.5), px(im, 0.75, 0.5)
    assert a_.mean() < 70 and b_.mean() > 130 and b_[2] > b_[0] + 15, (a_, b_)
    print("OK  Röntgen")

    # 12) Zeitfenster: außerhalb unverändert
    im = frames(solid("0x808080"), "thermal", 100, dur=2.0, window=(1.0, 1.5))
    assert gray(px(im[5], 0.5, 0.5), 6) and not gray(px(im[int(1.2 * FPS)], 0.5, 0.5), 40) and gray(px(im[int(1.8 * FPS)], 0.5, 0.5), 6)
    print("OK  Zeitfenster")
    print("ALLES OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
