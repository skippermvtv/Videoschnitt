"""Untertitel und Textanimationen mit echtem FFmpeg; Spracherkennung mit Attrappen-Programm."""
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")          # eigener Benutzerordner für whisper-Test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, subtitles  # noqa: E402
from app.core.project import Clip, Project, SubtitleCue, TextLayer, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
FONT = str(Path(__file__).resolve().parent.parent / "fonts" / "ClipForgeMetal.ttf")


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def black_video(dur=6):
    f = tmp / "black.mp4"
    sh("-f", "lavfi", "-i", f"color=c=black:s=320x180:r=25:d={dur}", "-f", "lavfi", "-i", f"sine=frequency=300:duration={dur}",
       "-c:v", "libx264", "-c:a", "aac", "-shortest", str(f))
    return f


def project():
    f = black_video()
    i = probe(str(f))
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(f), i.duration, has_audio=True, width=i.width, height=i.height)]
    return p


def render(p, name):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True)
    exporter.run(cmd, total)
    return out


def ink(video, t):
    png = tmp / "f.png"
    sh("-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(png))
    im = np.array(Image.open(png).convert("L"))
    return int((im > 128).sum()), im


def light(video, t):
    return int(ink(video, t)[1].astype(np.int64).sum())


def main() -> int:
    # SRT
    cues = [SubtitleCue(1.0, 3.5, "Hallo Welt"), SubtitleCue(62.5, 64.0, "Zeile\nzwei")]
    assert subtitles.parse_srt(subtitles.to_srt(cues)) == cues
    f = tmp / "t.srt"; subtitles.write_srt(str(f), cues); assert subtitles.read_srt(str(f)) == cues
    print("OK  SRT lesen/schreiben")

    # Jede Animation rendert, zeigt Text in der Mitte und nichts außerhalb des Fensters
    for anim in ("none", "fade", "slide_up", "slide_left", "bounce", "typewriter", "shake", "blink"):
        p = project()
        p.texts = [TextLayer(text="Hallo Welt, das ist ein Test", start=1.0, end=4.0, size_pct=14, color="white",
                             border_color="white", font=FONT, anim=anim, anim_dur=0.5)]
        v = render(p, f"anim_{anim}")
        before, _ = ink(v, 0.5)
        mid, _ = ink(v, 2.5) if anim != "blink" else (max(ink(v, 2.0)[0], ink(v, 2.1)[0], ink(v, 2.4)[0]), None)
        after, _ = ink(v, 5.0)
        assert before == 0 and after == 0, (anim, before, after)
        assert mid > 200, (anim, mid)
    print("OK  8 Textanimationen rendern")

    # Fade: am Anfang weniger Tinte als später; Schreibmaschine: Buchstaben wachsen
    p = project()
    p.texts = [TextLayer(text="Hallo Welt", start=1.0, end=5.0, size_pct=14, color="white", border_color="white",
                         font=FONT, anim="fade", anim_dur=1.0)]
    v = render(p, "fade"); a, b = light(v, 1.3), light(v, 3.0)
    assert 0 < a < b * 0.6, (a, b)
    p.texts[0].anim = "typewriter"; p.texts[0].anim_dur = 0.5
    v = render(p, "type"); a, b = ink(v, 1.15)[0], ink(v, 4.0)[0]
    assert 0 <= a < b * 0.6 and b > 300, (a, b)
    print("OK  Fade und Schreibmaschine verlaufen")

    # Untertitel mit Stil
    p = project()
    p.subtitles = [SubtitleCue(0.5, 2.0, "Erster Satz"), SubtitleCue(2.5, 4.5, "Zweiter Satz, etwas länger"),
                   SubtitleCue(5.0, 5.9, "Dritter")]
    p.sub_style.font = FONT; p.sub_style.color = "white"; p.sub_style.border_color = "white"; p.sub_style.size_pct = 12
    p.sub_style.box = True; p.sub_style.anim = "fade"
    v = render(p, "subs")
    assert ink(v, 0.2)[0] == 0 and ink(v, 1.2)[0] > 100 and ink(v, 2.2)[0] < 10 and ink(v, 3.5)[0] > 100
    print("OK  Untertitel (Zeiten, Kasten, Fade)")

    # Lange Einträge teilen
    long = subtitles.split_long([SubtitleCue(0, 12, " ".join(["wort"] * 60))])
    assert len(long) >= 3 and abs(long[-1].end - 12) < 0.01 and all(len(c.text) <= 90 for c in long)
    print("OK  lange Untertitel werden geteilt")

    # Spracherkennung: Attrappe statt whisper.cpp
    assert subtitles.find_whisper() is None
    wd = subtitles.whisper_dir()
    # Die Attrappe ist ein kleines Python-Skript; ein Aufrufer-Skript startet es (Linux: sh, Windows: .bat)
    fake = wd / "fake_whisper.py"
    fake.write_text(
        "import sys\n"
        "a = sys.argv[1:]\n"
        "of = a[a.index('-of') + 1]\n"
        "open(of + '.srt', 'w', encoding='utf-8').write('1\\n00:00:00,500 --> 00:00:02,000\\nHallo aus der Attrappe\\n\\n')\n",
        encoding="utf-8")
    if os.name == "nt":
        exe = wd / "whisper-cli.bat"
        exe.write_text(f'@"{sys.executable}" "{fake}" %*\r\n', encoding="ascii")
        # .bat wird vom Programm nicht automatisch gesucht (nur .exe): Fundort für den Test festlegen
        subtitles.find_whisper = lambda: (str(exe), str(wd / "ggml-base.bin"))
    else:
        exe = wd / "whisper-cli"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n')
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    (wd / "ggml-base.bin").write_bytes(b"x" * 10)
    assert subtitles.find_whisper() is not None
    p = project()
    got = subtitles.transcribe_project(p, "de")
    assert got and got[0].text == "Hallo aus der Attrappe" and abs(got[0].start - 0.5) < 1e-6
    assert p.texts == [] and p.subtitles == []
    print("OK  automatische Untertitel (Ablauf mit Attrappe)")

    # Speichern/Laden
    p.subtitles = got; p.sub_style.anim = "fade"
    f = tmp / "p.cforge"; p.save(str(f)); q = Project.load(str(f))
    assert q.subtitles == got and q.sub_style.anim == "fade"
    import json
    d = json.loads(f.read_text(encoding="utf-8")); d.pop("subtitles"); d.pop("sub_style")
    f.write_text(json.dumps(d), encoding="utf-8")
    assert Project.load(str(f)).subtitles == []
    print("OK  Speichern/Laden, altes Projekt")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
