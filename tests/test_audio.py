"""Audio-Test mit echtem FFmpeg: Ton trennen, Musikspur, Loop, Ducking, Spur stumm, Lautheit.

Die Töne werden per FFT geprüft: Video-Ton = 440 Hz, Musik = 1000 Hz.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import exporter  # noqa: E402
from app.core.project import AudioClip, Clip, Project, probe, probe_audio  # noqa: E402
from app.paths import find_binary  # noqa: E402

ff = find_binary("ffmpeg")
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())


def sh(*a):
    subprocess.run([ff, "-v", "error", "-y", *a], check=True)


def make_media():
    v_audio = tmp / "v_audio.mp4"      # 3 s Video mit 440 Hz
    v_silent = tmp / "v_silent.mp4"    # 3 s Video ohne Ton
    music = tmp / "music.wav"          # 2 s 1000 Hz
    sh("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=3", "-f", "lavfi",
       "-i", "sine=frequency=440:duration=3", "-af", "volume=4", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(v_audio))
    sh("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=3", "-c:v", "libx264", str(v_silent))
    sh("-f", "lavfi", "-i", "sine=frequency=1000:duration=2", "-af", "volume=4", str(music))
    return v_audio, v_silent, music


def render(proj: Project, name: str) -> Path:
    out = tmp / f"{name}.mp4"
    cmd, total, _ = exporter.build_command(proj, str(out), draft=True)
    exporter.run(cmd, total)
    info = probe(str(out))
    assert abs(info.duration - proj.duration) < 0.35, (name, info.duration, proj.duration)
    assert info.has_audio
    return out


def samples(path: Path) -> np.ndarray:
    r = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32)


def level(x: np.ndarray, t0: float, t1: float, freq: float) -> float:
    seg = x[int(t0 * 16000):int(t1 * 16000)]
    if len(seg) < 800:
        return 0.0
    seg = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg)) / len(seg) * 4
    f = np.fft.rfftfreq(len(seg), 1 / 16000)
    return float(spec[(f > freq - 15) & (f < freq + 15)].max())


def base() -> Project:
    va, vs, _ = make_media_cache
    ca = probe(str(va)); cs = probe(str(vs))
    p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
    p.clips = [Clip(str(va), ca.duration, has_audio=True, width=ca.width, height=ca.height),
               Clip(str(vs), cs.duration, has_audio=False, width=cs.width, height=cs.height)]
    return p


def main() -> int:
    global make_media_cache
    make_media_cache = make_media()
    _, _, music = make_media_cache
    mdur = probe_audio(str(music))
    assert abs(mdur - 2.0) < 0.1

    # 1) Ton trennen und verschieben
    p = base()
    a = p.detach_audio(0)
    assert a and p.clips[0].audio_detached and a.track == 1
    assert p.detach_audio(0) is None
    a.link_offset = 3.0
    p.sync_linked()
    assert abs(a.start - 3.0) < 1e-6
    x = samples(render(p, "detach"))
    assert level(x, 0.5, 2.5, 440) < 0.02, "Original-Ton darf nach dem Trennen nicht mehr am Clip liegen"
    assert level(x, 3.3, 5.7, 440) > 0.3, "Getrennter Ton fehlt an der neuen Stelle"
    print("OK  Ton trennen + verschieben")

    # 2) wieder verbinden
    assert p.reattach_audio(0) and not p.clips[0].audio_detached and not p.audio_clips
    x = samples(render(p, "reattach"))
    assert level(x, 0.5, 2.5, 440) > 0.3
    print("OK  Wieder verbinden")

    # 3) Musik mit Loop ab 1 s bis zum Ende
    p = base()
    p.audio_clips.append(AudioClip(str(music), mdur, start=1.0, track=2, loop=True, volume=0.5, fade_in=0.2, fade_out=0.3))
    x = samples(render(p, "loop"))
    assert level(x, 0.1, 0.8, 1000) < 0.02, "Musik beginnt zu früh"
    assert level(x, 1.5, 2.5, 1000) > 0.15
    assert level(x, 4.5, 5.5, 1000) > 0.15, "Loop füllt das Video nicht bis zum Ende"
    assert level(x, 1.5, 2.5, 440) > 0.3, "Video-Ton muss neben der Musik bleiben"
    print("OK  Musik-Loop und Mix")

    # 4) Ducking
    p = base()
    p.audio_clips.append(AudioClip(str(music), mdur, start=0.0, track=2, loop=True, volume=0.5))
    x0 = samples(render(p, "noduck"))
    p.ducking = True; p.ducking_amount = 0.8
    x1 = samples(render(p, "duck"))
    plain = level(x0, 0.6, 2.4, 1000)
    ducked = level(x1, 0.6, 2.4, 1000)
    free = level(x1, 3.6, 5.4, 1000)
    print(f"    Musik ohne Ducking {plain:.3f}, mit Ducking {ducked:.3f}, nach der Sprache {free:.3f}")
    assert ducked < plain * 0.5, "Ducking senkt die Musik nicht genug"
    assert free > plain * 0.7, "Musik kommt nach dem Ton nicht zurück"
    print("OK  Ducking")

    # 5) Spur stumm / Spurlautstärke
    p = base()
    p.audio_clips.append(AudioClip(str(music), mdur, start=0.0, track=2, loop=True))
    p.track_mute["2"] = True
    x = samples(render(p, "mute"))
    assert level(x, 3.5, 5.5, 1000) < 0.02
    p.track_mute = {}; p.track_volume["2"] = 0.2
    x = samples(render(p, "vol"))
    v = level(x, 3.5, 5.5, 1000)
    assert 0.07 < v < 0.13, v
    print("OK  Spur stumm / Spurlautstärke")

    # 6) Lautheit
    p = base()
    p.audio_clips.append(AudioClip(str(music), mdur, start=0.0, track=2, loop=True, volume=0.3))
    p.normalize = True
    x = samples(render(p, "loud"))
    assert level(x, 3.5, 5.5, 1000) > 0.1
    assert float(np.abs(x).max()) <= 1.0
    print("OK  Lautheit normalisieren")

    # 7) Speichern/Laden + altes Projekt
    p = base(); p.detach_audio(0)
    f = tmp / "t.cforge"; p.save(str(f))
    q = Project.load(str(f))
    assert q.clips[0].audio_detached and len(q.audio_clips) == 1 and q.audio_clips[0].link == q.clips[0].uid
    old = json.loads(f.read_text(encoding="utf-8"))
    for k in ("audio_clips", "track_volume", "track_mute", "ducking", "ducking_amount", "normalize"):
        old.pop(k, None)
    for c in old["clips"]:
        c.pop("audio_detached", None); c.pop("uid", None)
    f.write_text(json.dumps(old), encoding="utf-8")
    r = Project.load(str(f))
    assert r.audio_clips == [] and not r.clips[0].audio_detached
    render(r, "old")
    print("OK  Speichern/Laden, altes Projekt")
    # 8) Wellenform
    from app.core import waveform
    png = waveform.render(str(music))
    assert Path(png).stat().st_size > 500 and waveform.render(str(music)) == png
    print("OK  Wellenform")
    print("ALLES OK ->", tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
