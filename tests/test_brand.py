"""Marken-Vorlage: speichern/laden, Intro/Outro/Logo einsetzen (Spuren rücken mit), ersetzen statt verdoppeln, entfernen, echter Export."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata_brand")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paths  # noqa: E402
from app.core import brand, exporter  # noqa: E402
from app.core.project import AudioClip, Clip, OverlayClip, Project, SubtitleCue, TextLayer, probe  # noqa: E402

ff = paths.find_binary("ffmpeg")


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


# ---------------------------------------------------------------- Speichern / Laden
check(brand.load().empty() and brand.load().corner == "br", "Standard ohne Datei")
k = brand.Kit(intro="a.mp4", outro="b.png", image_seconds=99, logo="l.png", corner="xx", size=500, opacity=-5, auto_new=True)
check(brand.save(k), "speichern")
k2 = brand.load()
check(k2.intro == "a.mp4" and k2.outro == "b.png" and k2.image_seconds == 30.0 and k2.corner == "br" and k2.size == 60.0 and k2.opacity == 0.0 and k2.auto_new, k2)
(paths.user_dir() / "brand.json").write_text("{kaputt", encoding="utf-8")
check(brand.load().empty(), "kaputte Datei → Standard")
(paths.user_dir() / "brand.json").write_text('{"intro": 5, "size": "viel", "unbekannt": 1}', encoding="utf-8")
k3 = brand.load()
check(k3.intro == "" and k3.size == 14.0, k3)
print("OK  Speichern und Laden")

# ---------------------------------------------------------------- Dateien
intro = tmp / "brand_intro.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=1.5", "-f", "lavfi", "-i", "sine=duration=1.5",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(intro)], check=True)
outro = tmp / "brand_outro.png"
logo = tmp / "brand_logo.png"
for f, col in ((outro, "red"), (logo, "white")):
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=320x180", "-frames:v", "1", str(f)], check=True)
main = tmp / "brand_main.mp4"
subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4", "-f", "lavfi", "-i", "sine=duration=4",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(main)], check=True)
mi = probe(str(main))


def project():
    p = Project(format_id="youtube_16_9", export_id="fast_draft")
    p.clips = [Clip(str(main), mi.duration, has_audio=True, width=mi.width, height=mi.height) for _ in range(2)]
    p.audio_clips = [AudioClip(str(main), 4.0, start=1.0, track=2, name="Musik")]
    p.overlays = [OverlayClip(str(logo), 3600.0, out_pt=2.0, start=2.0, is_image=True)]
    p.texts = [TextLayer(text="Hallo", start=1.0, end=3.0)]
    p.effects = [{"id": "glitch", "intensity": 50, "start": 3.0, "end": 5.0}]
    p.subtitles = [SubtitleCue(0.5, 1.5, "eins")]
    p.markers = [{"t": 2.0, "name": "M"}]
    return p


kit = brand.Kit(intro=str(intro), outro=str(outro), image_seconds=2.5, logo=str(logo), corner="tl", size=20, opacity=60)

# ---------------------------------------------------------------- Einsetzen
p = project()
d0 = p.duration
notes = brand.apply(p, kit)
check(notes == [], notes)
check(len(p.clips) == 4 and p.clips[0].brand == "intro" and p.clips[-1].brand == "outro" and p.clips[1].brand == "" and p.clips[2].brand == "", [c.brand for c in p.clips])
check(abs(p.clips[0].length - 1.5) < 0.1 and abs(p.clips[-1].length - 2.5) < 1e-9 and p.clips[-1].is_image and not p.clips[0].is_image, (p.clips[0].length, p.clips[-1].length))
dt = p.clips[0].length
check(abs(p.duration - (d0 + dt + 2.5)) < 1e-6, (p.duration, d0))
check(abs(p.audio_clips[0].start - (1.0 + dt)) < 1e-3 and abs(p.overlays[0].start - (2.0 + dt)) < 1e-3, (p.audio_clips[0].start, p.overlays[0].start))
check(abs(p.texts[0].start - (1.0 + dt)) < 1e-3 and abs(p.texts[0].end - (3.0 + dt)) < 1e-3, "Texte rücken mit")
check(abs(p.effects[0]["start"] - (3.0 + dt)) < 1e-3 and abs(p.effects[0]["end"] - (5.0 + dt)) < 1e-3, p.effects)
check(abs(p.subtitles[0].start - (0.5 + dt)) < 1e-3 and abs(p.markers[0]["t"] - (2.0 + dt)) < 1e-3, "Untertitel und Marker rücken mit")
check(p.watermark == str(logo) and p.wm_corner == "tl" and p.wm_size == 20 and p.wm_opacity == 60, "Logo")
print("OK  Einsetzen: Intro, Outro, Logo, Spuren rücken mit")

# erneut einsetzen: ersetzt, verdoppelt nicht, Spuren bleiben gleich
before = (p.audio_clips[0].start, p.texts[0].start, p.markers[0]["t"], len(p.clips), p.duration)
brand.apply(p, kit)
after = (p.audio_clips[0].start, p.texts[0].start, p.markers[0]["t"], len(p.clips), p.duration)
check(all(abs(a - b) < 1e-3 for a, b in zip(before, after)), (before, after))
# Vorlage ändern: nur Outro
brand.apply(p, brand.Kit(outro=str(outro), image_seconds=1.0))
check(len(p.clips) == 3 and p.clips[0].brand == "" and p.clips[-1].brand == "outro" and abs(p.clips[-1].length - 1.0) < 1e-9, [c.brand for c in p.clips])
check(abs(p.audio_clips[0].start - 1.0) < 1e-3 and abs(p.texts[0].start - 1.0) < 1e-3, "Intro entfernt → Spuren wieder zurück")
print("OK  Ersetzen statt verdoppeln")

# Entfernen: zurück zum Ausgangszustand
p = project()
brand.apply(p, kit)
n = brand.remove(p, kit)
q = project()
check(n == 2 and len(p.clips) == 2 and abs(p.duration - q.duration) < 1e-6, (n, len(p.clips)))
check(abs(p.audio_clips[0].start - 1.0) < 1e-3 and abs(p.overlays[0].start - 2.0) < 1e-3 and abs(p.effects[0]["end"] - 5.0) < 1e-3
      and abs(p.subtitles[0].end - 1.5) < 1e-3 and abs(p.markers[0]["t"] - 2.0) < 1e-3, "alles wieder an alter Stelle")
check(p.watermark == "", "Logo der Vorlage entfernt")
p.watermark = "anderes.png"
brand.remove(p, kit)
check(p.watermark == "anderes.png", "fremdes Logo bleibt")
print("OK  Entfernen")

# Fehlende Dateien
p = project()
notes = brand.apply(p, brand.Kit(intro=str(tmp / "nix.mp4"), outro=str(tmp / "nix.png"), logo=str(tmp / "nix_logo.png")))
check(len(notes) == 3 and len(p.clips) == 2 and p.watermark == "", notes)
bad = tmp / "brand_kaputt.mp4"
bad.write_bytes(b"kein video")
notes = brand.apply(p, brand.Kit(intro=str(bad)))
check(len(notes) == 1 and "lässt sich nicht lesen" in notes[0] and len(p.clips) == 2, notes)
print("OK  Fehlende/defekte Dateien")

# Neue Clips kommen vor das Outro
p = project()
brand.apply(p, kit)
check(brand.insert_position(p) == len(p.clips) - 1, brand.insert_position(p))
check(brand.insert_position(Project()) == 0, "leer")

# Speichern/Laden des Projekts behält die Markierung
p2 = Project.from_json(p.to_json())
check([c.brand for c in p2.clips] == ["intro", "", "", "outro"], [c.brand for c in p2.clips])

# ---------------------------------------------------------------- Echt exportieren
out = tmp / "brand_out.mp4"
cmd, total, _ = exporter.build_command(p, str(out), draft=True)
exporter.run(cmd, total)
oi = probe(str(out))
check(abs(oi.duration - p.duration) < 0.5, (oi.duration, p.duration))
print(f"OK  Export mit Intro/Outro/Logo ({oi.duration:.1f} s)")
print("ALLES OK")
