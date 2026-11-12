"""Echte Wortzeiten (Whisper-JSON): Auslesen, Zuordnen, Teilen, Karaoke-Export (echtes FFmpeg, Pixelprüfung)."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, karaoke  # noqa: E402
from app.core import subtitles as subs  # noqa: E402
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
    # --- Whisper-JSON auslesen (nachgebaut nach der Ausgabe von whisper.cpp -ojf) ---
    def tok(text, a, b):
        return {"text": text, "offsets": {"from": a, "to": b}, "id": 1, "p": 0.9}

    js = {"transcription": [
        {"offsets": {"from": 1000, "to": 3000}, "text": " Hallo, wie geht's",
         "tokens": [tok("[_BEG_]", 1000, 1000), tok(" Hall", 1000, 1200), tok("o", 1200, 1400), tok(",", 1400, 1400), tok(" wie", 1700, 1900),
                    tok(" geht", 2200, 2500), tok("'s", 2500, 2800), tok("[_TT_150]", 3000, 3000)]},
        {"offsets": {"from": 3000, "to": 4500}, "text": " Schön",
         "tokens": [tok(" Sch", 3000, 3300), tok("ön", 3300, 3700)]},
        {"offsets": {"from": 5000, "to": 5000}, "text": " leer", "tokens": []},
        {"offsets": {"from": 5000, "to": 6000}, "text": " kaputt",
         "tokens": [tok(" kapp", 5000, 5400)]},
    ]}
    jf = tmp / "w.json"
    jf.write_text(json.dumps(js), encoding="utf-8")
    cues = subs.parse_whisper_json(str(jf))
    assert [c.text for c in cues] == ["Hallo, wie geht's", "Schön", "kaputt"], [c.text for c in cues]
    assert cues[0].words == [["Hallo,", 0.0, 0.4], ["wie", 0.7, 0.9], ["geht's", 1.2, 1.8]], cues[0].words
    assert cues[1].words == [["Schön", 0.0, 0.7]], cues[1].words
    assert cues[2].words == [], "Wörter passen nicht zum Text: keine echten Zeiten"
    print("OK  Whisper-JSON gelesen")

    # --- Zuordnen zur SRT ---
    srt_cues = [SubtitleCue(1.0, 3.0, "Hallo, wie geht's"), SubtitleCue(3.0, 4.5, "Schön"), SubtitleCue(5.0, 6.0, "kaputt")]
    att = subs.attach_words(srt_cues, cues)
    assert att[0].words == cues[0].words and att[2].words == [] and att[0].text == srt_cues[0].text
    assert subs.attach_words(srt_cues[:2], cues) == srt_cues[:2], "andere Anzahl: unverändert"
    wrong = [SubtitleCue(1.0, 3.0, "Anderer Text hier"), srt_cues[1], srt_cues[2]]
    assert subs.attach_words(wrong, cues)[0].words == [], "anderer Text: keine Wortzeiten"
    print("OK  Zuordnen")

    # --- Wortzeiten verwenden / verwerfen ---
    wt = karaoke.word_times("Hallo, wie geht's", 1.0, 3.0, cues[0].words)
    assert [round(a, 2) for _w, a, _b in wt] == [1.0, 1.7, 2.2], wt
    assert abs(wt[0][2] - 1.7) < 1e-6 and abs(wt[1][2] - 2.2) < 1e-6, "Pausen bis 0,4 s werden überbrückt: " + str(wt)
    assert abs(wt[2][2] - 2.8) < 1e-6, "das letzte Wort behält sein Ende"
    big = karaoke.word_times("A B", 0.0, 3.0, [["A", 0.0, 0.2], ["B", 2.0, 2.5]])
    assert abs(big[0][2] - 0.2) < 1e-6, "große Pausen bleiben Pausen"
    est = karaoke.word_times("Hallo, wie geht's", 1.0, 3.0)
    assert wt != est, "echte Zeiten unterscheiden sich von der Schätzung"
    assert karaoke.word_times("Hallo zusammen sagt", 1.0, 3.0, cues[0].words) == karaoke.word_times("Hallo zusammen sagt", 1.0, 3.0), "Text bearbeitet"
    assert karaoke.word_times("A B", 0, 2, [["A", 0, 1]]) == karaoke.word_times("A B", 0, 2), "falsche Anzahl"
    assert karaoke.word_times("A B", 0, 2, [["A", 1.5, 1.0], ["B", 0.0, 0.5]]) == karaoke.word_times("A B", 0, 2), "unsinnige Zeiten"
    assert karaoke.word_times("A B", 0, 2, [["A", "x", 1], ["B", 1, 2]]) == karaoke.word_times("A B", 0, 2), "Müll"
    t2 = karaoke.word_times("A B", 0, 1.0, [["A", 0.0, 0.2], ["B", 0.3, 5.0]])
    assert t2[-1][2] <= 1.0 + 1e-9, "nie über das Ende des Eintrags"
    print("OK  Wortzeiten prüfen")

    # --- Teilen langer Einträge behält die echten Zeiten ---
    words = [f"wort{i}" for i in range(14)]
    longcue = SubtitleCue(10.0, 24.0, " ".join(words), [[w, float(i), float(i) + 0.5] for i, w in enumerate(words)])
    parts = subs.split_long([longcue], max_chars=20)
    assert len(parts) >= 2 and " ".join(p.text for p in parts) == longcue.text, [p.text for p in parts]
    for part in parts:
        assert len(part.words) == len(part.text.split()), part
        assert abs(part.words[0][1]) < 1e-9, "Zeiten ab Beginn des Teils"
        assert part.end > part.start
    second = parts[1]
    first_idx = len(parts[0].text.split())
    assert abs(second.start - (10.0 + first_idx)) < 1e-6, (second.start, first_idx)
    assert abs(parts[-1].end - 24.0) < 1e-6
    plain = subs.split_long([SubtitleCue(0.0, 10.0, " ".join(words))], max_chars=20)
    assert all(p.words == [] for p in plain), "ohne echte Zeiten bleibt es wie bisher"
    print("OK  Teilen mit Wortzeiten")

    # --- Layer und Speichern/Laden ---
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [black("w.mp4", 4)]
    p.subtitles = [SubtitleCue(0.0, 3.0, "WWW WWW WWW", [["WWW", 0.0, 0.3], ["WWW", 2.0, 2.3], ["WWW", 2.5, 2.9]])]
    st = p.sub_style
    st.size_pct, st.position = 14.0, "center"
    st.karaoke, st.karaoke_color, st.karaoke_mode = True, "#ffd400", "stay"
    layers = cue_layers(p.subtitles, st)
    assert layers[0].words == p.subtitles[0].words
    q = Project.from_json(p.to_json())
    assert q.subtitles[0].words == p.subtitles[0].words
    d = json.loads(p.to_json())
    d["subtitles"][0].pop("words")
    assert Project.from_json(json.dumps(d)).subtitles[0].words == [], "altes Projekt"
    print("OK  Layer, Speichern/Laden")

    # --- Export: das zweite Wort leuchtet erst bei 2,0 s (die Schätzung hätte es schon bei 1,0 s) ---
    out = render(p, "words_stay")
    ys, ws = regions(frame(out, 1.2))
    assert ys[0] > 200 and ys[1] < 30 and ys[2] < 30, ("Mitte darf bei 1,2 s noch nicht leuchten", ys, ws)
    ys, ws = regions(frame(out, 2.2))
    assert ys[0] > 200 and ys[1] > 200 and ys[2] < 30, ("Mitte leuchtet ab 2,0 s", ys, ws)
    ys, ws = regions(frame(out, 2.7))
    assert min(ys) > 200, ("alle leuchten ab 2,5 s", ys, ws)
    est = Project.from_json(p.to_json())
    est.subtitles[0].words = []
    out2 = render(est, "words_est")
    ys, ws = regions(frame(out2, 1.2))
    assert ys[1] > 200, ("Schätzung zum Vergleich: Mitte leuchtet schon", ys, ws)
    print("OK  Karaoke mit echten Wortzeiten (Pixel)")
    print("ALLES OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
