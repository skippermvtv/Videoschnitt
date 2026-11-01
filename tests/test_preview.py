"""Vorschau ab Abspielkopf, Zwischenspeicher, Hardware-Encoder-Rückfall, Restzeit, Einstellungen."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter, preview, settings  # noqa: E402
from app.core.project import Clip, Project, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def two_color(name, c1, c2, each):
    f = tmp / name
    sh("-f", "lavfi", "-i", f"color=c={c1}:s=320x180:r=25:d={each}", "-f", "lavfi", "-i", f"color=c={c2}:s=320x180:r=25:d={each}",
       "-f", "lavfi", "-i", f"sine=frequency=440:duration={each * 2}", "-filter_complex", "[0][1]concat=n=2:v=1:a=0[v]",
       "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f))
    return f


def project():
    f = two_color("rb.mp4", "0xe01010", "0x1010e0", 4)      # 0–4 s rot, 4–8 s blau
    i = probe(str(f))
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(f), i.duration, has_audio=True, width=i.width, height=i.height)]
    return p


def render(p, name, **kw):
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), draft=True, **kw)
    exporter.run(cmd, total)
    return out, total


def px(video, t):
    png = tmp / "f.png"
    sh("-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(png))
    im = np.array(Image.open(png).convert("RGB")); h, w, _ = im.shape
    return tuple(int(v) for v in im[h // 2, w // 2]), (w, h)


def main() -> int:
    p = project()
    # 1) Ausschnitt ab 3,5 s, 3 s lang: erst Rot (bis 4 s), dann Blau
    out, total = render(p, "seg", start=3.5, max_seconds=3.0, preview_height=360)
    info = probe(str(out))
    assert abs(info.duration - 3.0) < 0.3 and abs(total - 3.0) < 0.05, (info.duration, total)
    a, size = px(out, 0.2); b, _ = px(out, 2.5)
    assert a[0] > 180 and a[2] < 80, a
    assert b[2] > 180 and b[0] < 80, b
    assert size == (640, 360), size
    print("OK  Vorschau ab Zeitpunkt, Länge, Auflösung 360p")

    # 2) Ende des Projekts: Start hinter dem Ende wird begrenzt, es kommt trotzdem ein Video
    out, total = render(p, "end", start=50.0, preview_height=240)
    assert probe(str(out)).duration > 0.3 and total <= 1.0
    print("OK  Start hinter dem Ende")

    # 3) Zwischenspeicher
    k1 = preview.key(p, 3.5, 8.0, 360)
    assert k1 == preview.key(p, 3.5, 8.0, 360)
    assert k1 != preview.key(p, 3.6, 8.0, 360) and k1 != preview.key(p, 3.5, 8.0, 540)
    p.clips[0].speed = 2.0
    assert k1 != preview.key(p, 3.5, 8.0, 360), "Änderung am Projekt muss neuen Schlüssel ergeben"
    p.clips[0].speed = 1.0
    assert k1 == preview.key(p, 3.5, 8.0, 360)
    for i in range(15):
        (preview.cache_dir() / f"x{i}.mp4").write_bytes(b"x"); time.sleep(0.01)
    assert preview.cleanup(max_files=12) >= 3 and len(list(preview.cache_dir().glob("*.mp4"))) <= 12
    print("OK  Zwischenspeicher und Aufräumen")

    # 4) Hardware-Encoder: Auswahl oder Rückfall – Export klappt in jedem Fall
    enc = exporter.hw_encoder()
    assert enc in (None, "h264_nvenc", "h264_qsv", "h264_amf")
    args, name = exporter.video_codec_args({"crf": 18, "x264_preset": "slow"}, False, True)
    assert name == (enc or "libx264") and "-c:v" in args
    args, name = exporter.video_codec_args({"crf": 18}, True, True)
    assert name == "libx264", "Entwurf bleibt immer bei libx264"
    out = tmp / "hw.mp4"
    cmd, total, _ = exporter.build_command(p, str(out), use_hw=True)
    exporter.run(cmd, total)
    assert abs(probe(str(out)).duration - 8.0) < 0.4
    print(f"OK  Export mit 'Grafikkarte nutzen' (Encoder: {enc or 'keiner gefunden → libx264'})")

    # 5) Rückwärts-Schutz
    p.clips[0].reverse = True; p.clips[0].duration = 500.0; p.clips[0].out_pt = 300.0
    try:
        exporter.build_command(p, str(tmp / "x.mp4"))
        raise AssertionError("Rückwärts bei 300 s hätte abgelehnt werden müssen")
    except exporter.ExportError as e:
        assert "Rückwärts" in str(e)
    print("OK  Rückwärts-Schutz bei langen Clips")

    # 6) Restzeit
    assert exporter.format_eta(1.0, 0.5) == "" and exporter.format_eta(10, 0.01) == ""
    assert exporter.format_eta(30, 0.5) == "noch ca. 0:30 min" and exporter.format_eta(60, 0.99) == "gleich fertig"
    assert exporter.format_eta(120, 0.25) == "noch ca. 6:00 min"
    print("OK  Restzeit-Anzeige")

    # 7) Einstellungen
    assert settings.load()["preview_height"] == 360 and settings.load()["hw_encode"] is False
    settings.save({"preview_height": 540, "hw_encode": True, "unbekannt": 1})
    s = settings.load(); assert s["preview_height"] == 540 and s["hw_encode"] is True and "unbekannt" not in s
    print("OK  Einstellungen")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
