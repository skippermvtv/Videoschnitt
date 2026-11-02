"""Umbenennung ClipForge -> FATE VIDEOSCHNITT: Name, Datenordner-Umzug, Schrift, Installer, Workflow, alte Projekte."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("FEHLER", msg)


base = Path(tempfile.mkdtemp())
os.environ["APPDATA"] = str(base)
from app import paths, version  # noqa: E402

check(version.APP_NAME == "FATE VIDEOSCHNITT" and version.APP_SLUG == "FATE-VIDEOSCHNITT", "Name")

# Datenordner: alter Ordner wird umbenannt, Inhalt bleibt
old = base / "ClipForge"
(old / "whisper").mkdir(parents=True)
(old / "settings.json").write_text('{"preview_height": 540}', encoding="utf-8")
(old / "whisper" / "ggml-base.bin").write_bytes(b"x" * 10)
d = paths.user_dir()
check(d == base / "FATE VIDEOSCHNITT" and not old.exists(), f"Umzug: {d}, alt existiert noch: {old.exists()}")
check((d / "settings.json").read_text(encoding="utf-8") == '{"preview_height": 540}' and (d / "whisper" / "ggml-base.bin").exists(),
      "Inhalt nach dem Umzug fehlt")
check(paths.user_dir() == d, "zweiter Aufruf ändert den Ordner")
from app.core import settings  # noqa: E402
check(settings.load()["preview_height"] == 540, "Einstellungen gehen beim Umzug verloren")
# Beide Ordner vorhanden: der neue gewinnt, nichts wird überschrieben
(base / "ClipForge").mkdir()
(base / "ClipForge" / "x.txt").write_text("alt", encoding="utf-8")
check(paths.user_dir() == d and (base / "ClipForge" / "x.txt").exists(), "alter Ordner darf nicht überschrieben werden")
# Frische Installation: nur der neue Ordner
base2 = Path(tempfile.mkdtemp())
os.environ["APPDATA"] = str(base2)
check(paths.user_dir() == base2 / "FATE VIDEOSCHNITT" and not (base2 / "ClipForge").exists(), "Neuinstallation")
os.environ["APPDATA"] = str(base)
print("OK  Datenordner-Umzug")

# Schrift: neuer Name, alte Pfade werden gefunden
from fontTools.ttLib import TTFont  # noqa: E402
ttf = ROOT / "fonts" / "FateMetal.ttf"
check(ttf.exists() and not (ROOT / "fonts" / "ClipForgeMetal.ttf").exists(), "Schriftdatei")
fam = {r.toUnicode() for r in TTFont(str(ttf))["name"].names if r.nameID in (1, 4, 6)}
check(not any("ClipForge" in x for x in fam) and "FATE Metal" in fam, f"Namenstabelle: {fam}")
check(paths.resolve_font(str(ttf)) == str(ttf), "vorhandene Schrift bleibt")
check(paths.resolve_font("C:\\Programme\\ClipForge\\fonts\\ClipForgeMetal.ttf") == str(paths.bundle_dir() / "fonts" / "FateMetal.ttf"),
      "alter Schriftpfad wird nicht gefunden")
check(paths.resolve_font("/nirgends/gibt_es_nicht.ttf") == "" and paths.resolve_font("") == "", "unbekannte Schrift -> Standardschrift")
# Export mit dem alten Schriftpfad funktioniert noch
import subprocess  # noqa: E402
from app.core import exporter  # noqa: E402
from app.core.project import Clip, Project, TextLayer, probe  # noqa: E402
from app.paths import find_binary  # noqa: E402
tmp = Path(tempfile.mkdtemp())
v = tmp / "v.mp4"
subprocess.run([find_binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=25:d=2", "-c:v", "libx264", str(v)], check=True)
i = probe(str(v))
p = Project(format_id="youtube_16_9", export_id="youtube_1080p")
p.clips = [Clip(str(v), i.duration, has_audio=False, width=i.width, height=i.height)]
p.texts = [TextLayer(text="Alt", start=0.0, end=2.0, font="C:\\Alt\\ClipForgeMetal.ttf", size_pct=10.0)]
cmd, total, _ = exporter.build_command(p, str(tmp / "o.mp4"), draft=True)
exporter.run(cmd, total)
check((tmp / "o.mp4").exists() and "FateMetal.ttf" in " ".join(cmd), "Export mit altem Schriftpfad")
print("OK  Schrift „FATE Metal“ und alte Pfade")

# Installer, Workflow, Build-Skript: neuer Name überall, alter Name nur zum Aufräumen
iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
check('MyAppName "FATE VIDEOSCHNITT"' in iss and "FATE-VIDEOSCHNITT-Setup" in iss and "dist\\FATE-VIDEOSCHNITT" in iss, "installer.iss")
check(iss.count("ClipForge.exe") == 1 and "[InstallDelete]" in iss, "alte ClipForge.exe wird nur im InstallDelete erwähnt")
check("AppId={{B6F3C2E4-5A7D-4F1E-9C0A-3D2E8B7A1F55}" in iss, "AppId muss gleich bleiben, damit das Setup die alte Installation ersetzt")
wf = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
check("--name FATE-VIDEOSCHNITT" in wf and "FATE-VIDEOSCHNITT-Setup.exe" in wf and "ClipForge" not in wf, "build.yml")
bat = (ROOT / "build.bat").read_text(encoding="utf-8")
check("--name FATE-VIDEOSCHNITT" in bat and "dist\\FATE-VIDEOSCHNITT" in bat and "ClipForge" not in bat, "build.bat")
# Der Update-Check findet die neue Setup-Datei (Name endet auf setup.exe)
check("FATE-VIDEOSCHNITT-Setup.exe".lower().endswith("setup.exe"), "Updater erkennt die Setup-Datei nicht")
print("OK  Installer, Workflow, Build-Skript")

# Altes Projekt (aus ClipForge) lädt weiter
old_proj = {"format_id": "youtube_16_9", "clips": [], "effects": [{"id": "bw", "intensity": 80}], "texts": []}
f = tmp / "alt.cforge"
f.write_text(json.dumps(old_proj), encoding="utf-8")
q = Project.load(str(f))
check(q.effects == [{"id": "bw", "intensity": 80}], "altes Projekt")
print("OK  Altes Projekt lädt")
print("ALLES OK" if not fails else f"{len(fails)} FEHLER")
sys.exit(1 if fails else 0)
