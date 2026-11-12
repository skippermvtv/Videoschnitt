"""Szenenerkennung: Analyse mit Farbflächen, Schnittberechnung, Clip teilen, Export (echtes FFmpeg)."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, scenes  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def blocks(name, colors, each, size="320x180"):
    f = tmp / name
    ins = []
    for c in colors:
        ins += ["-f", "lavfi", "-i", f"color=c={c}:s={size}:r=25:d={each}"]
    fc = "".join(f"[{i}:v]" for i in range(len(colors))) + f"concat=n={len(colors)}:v=1:a=0[v]"
    sh(*ins, "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f))
    return f


def clip_of(f):
    i = probe(str(f))
    return Clip(str(f), i.duration, has_audio=i.has_audio, width=i.width, height=i.height)


def close(a, b, tol=0.12):
    return abs(a - b) <= tol


def main() -> int:
    # --- parse ---
    txt = ("[Parsed_showinfo_2 @ 0x1] n:   0 pts:  37 pts_time:1.48 pos: 1\n[Parsed_showinfo_2 @ 0x1] n: 1 pts: 75 pts_time:3\n"
           "[Parsed_scale_0 @ 0x1] pts_time:9\nrauschen\n")
    assert scenes.parse(txt) == [1.48, 3.0] and scenes.parse("") == []
    print("OK  FFmpeg-Ausgabe lesen")

    f = blocks("four.mp4", ["black", "white", "0x303030", "0xd0d0d0"], 1.5)
    c = clip_of(f)
    t = scenes.detect(c, 0.3)
    assert len(t) == 3 and close(t[0], 1.5) and close(t[1], 3.0) and close(t[2], 4.5), t
    print("OK  Szenenwechsel gefunden", [round(x, 2) for x in t])

    # sehr ähnliche Flächen: bei 0.3 nichts, bei sehr niedriger Schwelle etwas
    g = blocks("subtle.mp4", ["0x808080", "0x868686", "0x808080"], 1.5)
    assert scenes.detect(clip_of(g), 0.3) == []
    print("OK  kleine Änderungen lösen nichts aus")

    # Ausschnitt: Zeiten bleiben Quell-Sekunden
    c.in_pt, c.out_pt = 2.0, 5.5
    t2 = scenes.detect(c, 0.3)
    assert len(t2) == 2 and close(t2[0], 3.0) and close(t2[1], 4.5), t2
    c.in_pt, c.out_pt = 0.0, c.duration
    print("OK  Ausschnitt")

    # --- Schnitte ---
    assert scenes.cuts_from([0.2, 1.5, 1.6, 3.0, 5.9], 0.0, 6.0, 0.5) == [1.5, 3.0], "zu nah an Anfang, Ende und aneinander"
    assert scenes.ranges([1.5, 3.0], 0.0, 6.0) == [(0.0, 1.5), (1.5, 3.0), (3.0, 6.0)]
    assert "2 Schnitte" in scenes.describe([1.5, 3.0], 0.0, 6.0) and "Keine" in scenes.describe([], 0, 6)
    print("OK  Schnitte berechnen")

    # --- Clip teilen ---
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [clip_of(f)]
    p.clips[0].transition, p.clips[0].transition_dur = "fade", 0.5
    used = scenes.apply(p, 0, t)
    assert used == [0, 1, 2, 3] and len(p.clips) == 4
    assert all(close(x.in_pt, w, 0.1) for x, w in zip(p.clips, [0.0, 1.5, 3.0, 4.5]))
    assert all(close(x.out_pt, w, 0.1) for x, w in zip(p.clips, [1.5, 3.0, 4.5, 6.0]))
    assert all(abs(a.out_pt - b.in_pt) < 1e-9 for a, b in zip(p.clips, p.clips[1:])), "lückenlos"
    assert [x.transition for x in p.clips] == ["", "", "", "fade"] and len({x.uid for x in p.clips}) == 4
    assert abs(p.duration - 6.0) < 0.1
    for bad, msg in ((dict(ramp_id="x"), "Tempokurve"), (dict(reverse=True), "rückwärts")):
        q = Project(); q.clips = [clip_of(f)]
        for k, v in bad.items():
            setattr(q.clips[0], k, v)
        try:
            scenes.apply(q, 0, t)
            raise AssertionError(bad)
        except scenes.SceneError as e:
            assert msg in str(e), e
    try:
        scenes.apply(Project(), 0, t)
        raise AssertionError("kein Clip")
    except scenes.SceneError:
        pass
    print("OK  Clip geteilt, Fehlerfälle")

    # --- Export bleibt gleich lang ---
    out = tmp / "scenes_out.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    assert close(probe(str(out)).duration, 6.0, 0.4)   # der Übergang „fade“ am letzten Stück ändert nichts, es folgt kein Clip
    print("OK  Export")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
