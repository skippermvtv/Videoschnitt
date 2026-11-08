"""Karaoke-Untertitel: Wortzeiten, Zeilenaufbau und Export (echtes FFmpeg, Pixelprüfung)."""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, karaoke, subpreview  # noqa: E402
from app.core.project import Clip, Project, SubtitleCue, probe  # noqa: E402
from app.core.subtitles import cue_layers  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def black(name, dur):
    f = tmp / name
    sh("-f", "lavfi", "-i", f"color=c=black:s=320x180:r=25:d={dur}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f))
    i = probe(str(f))
    return Clip(str(f), i.duration, has_audio=i.has_audio, width=i.width, height=i.height)


def render(p, name):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    return out


def frame(video, t):
    png = tmp / "kf.png"
    sh("-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(png))
    return np.array(Image.open(png).convert("RGB")).astype(int)


def yellow(im):
    return (im[..., 0] > 200) & (im[..., 1] > 170) & (im[..., 2] < 90)


def white(im):
    return (im[..., 0] > 215) & (im[..., 1] > 215) & (im[..., 2] > 215)


def regions(im):
    """(x0, x1) des Textes und die Anzahl gelber/weißer Pixel im linken, mittleren und rechten Drittel."""
    m = yellow(im) | white(im)
    xs = np.where(m.any(axis=0))[0]
    x0, x1 = xs.min(), xs.max() + 1
    cuts = np.linspace(x0, x1, 4).astype(int)
    ys = [int(yellow(im)[:, cuts[i]:cuts[i + 1]].sum()) for i in range(3)]
    ws = [int(white(im)[:, cuts[i]:cuts[i + 1]].sum()) for i in range(3)]
    return ys, ws


def main() -> int:
    # --- Wortzeiten ---
    wt = karaoke.word_times("Das ist ein kleiner Test", 2.0, 5.0)
    assert [w for w, _a, _b in wt] == ["Das", "ist", "ein", "kleiner", "Test"]
    assert abs(wt[0][1] - 2.0) < 1e-9 and abs(wt[-1][2] - 5.0) < 1e-9
    assert all(abs(a[2] - b[1]) < 1e-9 for a, b in zip(wt, wt[1:])), "lückenlos"
    assert wt[3][2] - wt[3][1] > wt[1][2] - wt[1][1], "längeres Wort bekommt mehr Zeit"
    assert karaoke.word_times("   ", 0, 1) == [] and len(karaoke.word_times("Hallo", 0, 0)) == 1
    print("OK  Wortzeiten")

    # --- Zeilenaufbau ---
    meas = lambda t: 10.0 * len(t)                       # noqa: E731
    rows = karaoke.layout("eins zwei drei vier fünf sechs sieben acht", meas, 400, 20)
    assert rows and len(rows) >= 2, rows
    assert [w for r in rows for w, _x in r] == "eins zwei drei vier fünf sechs sieben acht".split()
    for r in rows:
        assert all(r[i][1] < r[i + 1][1] for i in range(len(r) - 1))
        width = r[-1][1] + meas(r[-1][0]) - r[0][1]
        assert abs((r[0][1] + width / 2) - 200) < 1.0, "Zeile mittig"
    assert karaoke.layout("a b", meas, 400, 20)[0][0][1] > 0
    print("OK  Zeilenaufbau")

    # --- Export: Wort für Wort ---
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [black("k.mp4", 4)]
    p.subtitles = [SubtitleCue(0.0, 3.0, "WWW WWW WWW")]
    st = p.sub_style
    st.size_pct = 14.0
    st.position = "center"
    st.karaoke, st.karaoke_color, st.karaoke_mode = True, "#ffd400", "stay"
    out = render(p, "kar_stay")
    ys, ws = regions(frame(out, 0.5))
    assert ys[0] > 200 and ys[1] < 30 and ys[2] < 30 and ws[1] > 200 and ws[2] > 200 and ws[0] < 30, (ys, ws)
    ys, ws = regions(frame(out, 1.5))
    assert ys[0] > 200 and ys[1] > 200 and ys[2] < 30 and ws[2] > 200 and ws[0] < 30, (ys, ws)
    ys, ws = regions(frame(out, 2.7))
    assert min(ys) > 200 and max(ws) < 30, (ys, ws)
    assert not (yellow(frame(out, 3.6)) | white(frame(out, 3.6))).any(), "nach dem Eintrag kein Text"
    print("OK  Karaoke (Wörter bleiben hervorgehoben)", ys)

    p.sub_style.karaoke_mode = "active"
    out = render(p, "kar_active")
    ys, ws = regions(frame(out, 1.5))
    assert ys[1] > 200 and ys[0] < 30 and ys[2] < 30 and ws[0] > 200 and ws[2] > 200 and ws[1] < 30, (ys, ws)
    print("OK  Karaoke (nur das aktive Wort)")

    p.sub_style.karaoke_mode = "stay"
    p.sub_style.box = True
    out = render(p, "kar_box")
    im = frame(out, 0.5)
    assert (np.abs(im - 0).sum(axis=2) > 0).any() and yellow(im).any() and white(im).any()
    print("OK  Karaoke mit Kasten")

    # --- ohne Karaoke unverändert (normale Textebene) ---
    p.sub_style.karaoke = False
    cmd, _, _ = exporter.build_command(p, str(tmp / "nokar.mp4"), draft=True)
    assert "_k0.txt" not in " ".join(cmd) and not cue_layers(p.subtitles, p.sub_style)[0].karaoke
    print("OK  ohne Karaoke unverändert")

    # --- viele Einträge: langer Filtergraph läuft durch ---
    p.sub_style.karaoke = True
    p.sub_style.box = False
    p.clips = [black("long.mp4", 15)]
    p.subtitles = [SubtitleCue(i * 0.5, i * 0.5 + 0.48, "eins zwei drei vier fünf sechs") for i in range(30)]
    t0 = time.time()
    out = render(p, "kar_long")
    assert abs(probe(str(out)).duration - 15.0) < 0.4
    print(f"OK  30 Einträge x 6 Wörter ({time.time() - t0:.0f} s)")

    # --- Zu viele Wörter: normaler Text statt Karaoke ---
    p.clips = [black("long2.mp4", 3)]
    p.subtitles = [SubtitleCue(0.0, 2.5, " ".join(["wort"] * (karaoke.MAX_WORDS + 5)))]
    out = render(p, "kar_many")
    assert yellow(frame(out, 1.0)).sum() == 0 and white(frame(out, 1.0)).any()
    print("OK  zu lange Einträge werden normal gezeigt")

    # --- Untertitel-Vorschaubild ---
    p.clips = [black("prev.mp4", 6)]
    p.subtitles = [SubtitleCue(0.5, 1.5, "WWW WWW"), SubtitleCue(3.0, 5.0, "WWW WWW WWW")]
    p.sub_style.karaoke, p.sub_style.karaoke_mode, p.sub_style.position = True, "stay", "center"
    assert subpreview.pick_time(p, -1, 1) == 4.0, "Mitte des gewählten Eintrags"
    assert subpreview.pick_time(p, 1.0, -1) == 1.0, "Abspielkopf in einem Eintrag"
    assert subpreview.pick_time(p, 2.0, -1) == 1.0, "sonst Mitte des ersten Eintrags"
    p0 = Project(); assert subpreview.pick_time(p0, 0.0, -1) is None
    png = tmp / "subprev.png"
    if png.exists():
        png.unlink()
    subpreview.render(p, 4.0, str(png), height=360)
    im = np.array(Image.open(png).convert("RGB")).astype(int)
    assert im.shape[0] == 360 and yellow(im).sum() > 100 and white(im).sum() > 100, (im.shape, yellow(im).sum(), white(im).sum())
    print("OK  Untertitel-Vorschaubild")

    # --- Speichern/Laden, altes Projekt ---
    p.sub_style.karaoke_mode = "active"
    f = tmp / "kar.cforge"
    p.save(str(f))
    q = Project.load(str(f))
    assert q.sub_style.karaoke is True and q.sub_style.karaoke_mode == "active" and q.sub_style.karaoke_color == "#ffd400"
    import json
    d = json.loads(f.read_text(encoding="utf-8"))
    for key in ("karaoke", "karaoke_color", "karaoke_mode"):
        d["sub_style"].pop(key, None)
    f.write_text(json.dumps(d), encoding="utf-8")
    q = Project.load(str(f))
    assert q.sub_style.karaoke is False and q.sub_style.karaoke_mode == "stay"
    print("OK  Speichern/Laden, altes Projekt")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
