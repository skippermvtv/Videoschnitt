"""Stille entfernen: Analyse mit synthetischem Ton, Schnittberechnung, Clip teilen, Export (echtes FFmpeg)."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, silence  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def talk(name="talk.mp4"):
    """4,3 s: Ton 0–1, Stille 1–2, Ton 2–3, Stille 3–3,7, Ton 3,7–4,3."""
    f = tmp / name
    expr = "0.5*sin(2*PI*440*t)*(lt(t,1)+between(t,2,3)+gte(t,3.7))"
    sh("-f", "lavfi", "-i", "color=c=0x2040a0:s=320x180:r=25:d=4.3", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d=4.3",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f))
    return f


def clip_of(f):
    i = probe(str(f))
    return Clip(str(f), i.duration, has_audio=i.has_audio, width=i.width, height=i.height)


def close(a, b, tol=0.12):
    return abs(a - b) <= tol


def main() -> int:
    # --- parse ---
    txt = ("[silencedetect @ 0x1] silence_start: 1.0123\n[silencedetect @ 0x1] silence_end: 2.0 | silence_duration: 0.98\n"
           "[silencedetect @ 0x1] silence_start: 3.5\n")
    assert silence.parse(txt, 4.0) == [(1.0123, 2.0), (3.5, 4.0)]
    assert silence.parse("", 4.0) == [] and silence.parse("silence_end: 1.0", 4.0) == []
    print("OK  FFmpeg-Ausgabe lesen")

    f = talk()
    c = clip_of(f)
    # --- Analyse ---
    s = silence.detect(c, -35.0, 0.5)
    assert len(s) == 2 and close(s[0][0], 1.0) and close(s[0][1], 2.0) and close(s[1][0], 3.0) and close(s[1][1], 3.7), s
    s2 = silence.detect(c, -35.0, 0.8)
    assert len(s2) == 1 and close(s2[0][0], 1.0), s2
    c.in_pt, c.out_pt = 1.5, 4.3                                # Ausschnitt: Zeiten bleiben Quell-Sekunden
    s3 = silence.detect(c, -35.0, 0.3)
    assert close(s3[0][0], 1.5, 0.15) and close(s3[0][1], 2.0) and close(s3[1][0], 3.0), s3
    c.in_pt, c.out_pt = 0.0, c.duration
    print("OK  Pausen finden", [(round(a, 2), round(b, 2)) for a, b in s])

    # --- Schnitte und Stücke ---
    cuts = silence.cuts_from(s, 0.0, 4.3, pad=0.12)
    assert len(cuts) == 2 and close(cuts[0][0], 1.12, 0.05) and close(cuts[1][1], 3.58, 0.05), cuts
    assert len(silence.cuts_from(s, 0.0, 4.3, pad=0.4)) == 1, "zu kurzer Schnitt entfällt"
    assert silence.cuts_from([(1, 2), (1.95, 2.5)], 0, 5, pad=0.0) == [(1, 2.5)], "überlappende Pausen verschmelzen"
    ks = silence.keeps(cuts, 0.0, 4.3)
    assert len(ks) == 3 and ks[0][0] == 0.0 and ks[-1][1] == 4.3
    sm = silence.summary(cuts, 0.0, 4.3)
    assert sm["cuts"] == 2 and close(sm["removed"], 1.22, 0.1) and close(sm["after"], 3.08, 0.1) and sm["pieces"] == 3, sm
    sm2 = silence.summary(cuts, 0.0, 4.3, speed=2.0)
    assert close(sm2["removed"], sm["removed"] / 2, 0.01)
    assert "2 Pausen" in silence.describe(sm) and "Keine Pausen" in silence.describe(silence.summary([], 0, 4))
    print("OK  Schnitte, Stücke, Zahlen:", silence.describe(sm))

    # --- Clip teilen ---
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [clip_of(f)]
    p.clips[0].transition, p.clips[0].transition_dur = "fade", 0.5
    p.clips[0].keyframes = [{"t": 0.0, "zoom": 100, "x": 0, "y": 0}, {"t": 1.0, "zoom": 140, "x": 0, "y": 0}]
    idx = silence.apply(p, 0, cuts)
    assert idx == [0, 1, 2] and len(p.clips) == 3
    assert [round(x.in_pt, 2) for x in p.clips] == [0.0, round(cuts[0][1], 2), round(cuts[1][1], 2)]
    assert [x.transition for x in p.clips] == ["", "", "fade"], "nur das letzte Stück behält den Übergang"
    assert len({x.uid for x in p.clips}) == 3
    assert abs(p.duration - 3.08) < 0.15, p.duration
    assert p.clips[0].keyframes and p.clips[2].keyframes and p.clips[0].keyframes != p.clips[2].keyframes
    print("OK  Clip in Stücke geteilt, Dauer", round(p.duration, 2))

    # --- Fehlerfälle ---
    q = Project(); q.clips = [clip_of(f)]
    for bad, msg in (("ramp", "Tempokurve"), ("rev", "rückwärts")):
        c0 = q.clips[0]
        c0.ramp_id, c0.reverse = ("x" if bad == "ramp" else ""), bad == "rev"
        try:
            silence.apply(q, 0, cuts)
            raise AssertionError(bad)
        except silence.SilenceError as e:
            assert msg in str(e), e
    q.clips[0].ramp_id, q.clips[0].reverse = "", False
    try:
        silence.apply(q, 0, [(0.0, 4.3)])
        raise AssertionError("alles Stille")
    except silence.SilenceError as e:
        assert "nichts" in str(e)
    try:
        silence.apply(q, 5, cuts)
        raise AssertionError("kein Clip")
    except silence.SilenceError:
        pass
    mute = tmp / "mute.mp4"
    sh("-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mute))
    try:
        silence.detect(clip_of(mute))
        raise AssertionError("ohne Ton")
    except silence.SilenceError as e:
        assert "Ton" in str(e)
    print("OK  Fehlerfälle")

    # --- Export: kürzer, Ton ohne Knackser ---
    out = tmp / "silence_out.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    dur = probe(str(out)).duration
    assert close(dur, p.duration, 0.25), (dur, p.duration)
    raw = subprocess.run([ff, "-v", "error", "-i", str(out), "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(float)
    jump = np.abs(np.diff(a[1200:-1200])).max()          # Anfang und Ende der Datei (AAC-Auf-/Auslauf) zählen nicht
    assert jump < 3000, f"Knackser im Ton (Sprung {jump:.0f})"
    assert np.abs(a).max() > 8000, "Ton ist da"
    print(f"OK  Export {dur:.2f} s statt 4.30 s, größter Sprung im Ton {jump:.0f}")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
