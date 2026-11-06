"""Release-Prüfung: Symbol, Hilfe, Lizenzen, Presets, Workflow, Versionsstand und Dateien, die das Setup braucht."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import effects as fx  # noqa: E402
from app.core.helptext import SHORTCUTS, STEPS, help_html  # noqa: E402
from app import version  # noqa: E402

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("FEHLER", msg)


# Symbol
ico, png, logo = ROOT / "assets/icon.ico", ROOT / "assets/icon.png", ROOT / "assets/logo.png"
for f in (ico, png, logo):
    check(f.exists() and f.stat().st_size > 5000, f"{f.name} fehlt")
try:
    from PIL import Image
    im = Image.open(ico)
    sizes = im.info.get("sizes", set())
    check({(16, 16), (32, 32), (48, 48), (256, 256)} <= set(sizes), f"icon.ico ohne Standardgrößen: {sizes}")
    p = Image.open(png).convert("RGBA")
    check(p.size[0] == p.size[1] and p.getpixel((2, 2))[3] == 0 and p.getpixel((p.size[0] // 2, p.size[1] // 2))[3] == 255,
          "icon.png: Ecken müssen durchsichtig, Mitte deckend sein")
    lg = Image.open(logo)
    check(lg.size[0] == lg.size[1], "logo.png nicht quadratisch")
except ImportError:
    print("(Pillow fehlt – Symbolprüfung übersprungen)")
print("OK  Symbol")

# Hilfe
h = help_html()
for word in ("Importieren", "Exportieren", "Untertitel", "Strg+Z", "Vorschau", "Ton"):
    check(word in h, f"Hilfe erwähnt '{word}' nicht")
check(len(STEPS) >= 8 and len(SHORTCUTS) >= 6, "Hilfe zu kurz")
print("OK  Hilfe")

# Lizenzen
t = (ROOT / "THIRD_PARTY.txt").read_text(encoding="utf-8")
for word in ("FFmpeg", "PySide6", "fontTools", "PyInstaller", "Inno Setup", "whisper.cpp", "FATE Metal"):
    check(word in t, f"THIRD_PARTY.txt erwähnt {word} nicht")
import re as _r0
_re_req = _r0.compile(r"[A-Za-z0-9_.\-]+([<>=!~]=?[0-9.,<>=]+)?")
req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
check("PySide6" in req and "fonttools" in req.lower(), "requirements.txt unvollständig")
check("PySide6-Addons" in req, "requirements.txt ohne PySide6-Addons (QtMultimedia fehlt sonst beim Start)")
dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").lower()
check("numpy" in dev and "pillow" in dev, "requirements-dev.txt ohne numpy/pillow")
for _f in ("requirements.txt", "requirements-dev.txt"):   # pip kennt nur '#' als Kommentar; ';' bedeutet Bedingung
    for _i, _l in enumerate((ROOT / _f).read_text(encoding="utf-8").splitlines(), 1):
        _l = _l.strip()
        check(not _l or _l.startswith("#") or _re_req.fullmatch(_l), f"{_f} Zeile {_i} ist für pip ungültig: {_l}")
# Jedes Qt-Modul, das die Oberfläche importiert, muss im Paket Essentials oder Addons liegen
import re as _re
mods = set()
for f in (ROOT / "app").rglob("*.py"):
    mods |= set(_re.findall(r"from PySide6\.(Qt\w+) import", f.read_text(encoding="utf-8")))
check(mods <= {"QtCore", "QtGui", "QtWidgets", "QtMultimedia", "QtMultimediaWidgets"}, f"Unerwartete Qt-Module: {mods}")
print("OK  Lizenzen")

# Presets: gültiges JSON, eindeutige IDs, Looks verweisen auf vorhandene Effekte
ids_all = {}
for f in sorted((ROOT / "presets").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    ids = [d["id"] for d in data]
    check(len(ids) == len(set(ids)), f"{f.name}: doppelte IDs")
    check(all("name" in d for d in data), f"{f.name}: Eintrag ohne Namen")
    ids_all[f.stem] = ids
for look in json.loads((ROOT / "presets/looks.json").read_text(encoding="utf-8")):
    for e in look["effects"]:
        check(e[0] in fx.REGISTRY, f"Look {look['id']}: unbekannter Effekt {e[0]}")
for fmt in json.loads((ROOT / "presets/formats.json").read_text(encoding="utf-8")):
    check(fmt["default_export"] in ids_all["exports"], f"Format {fmt['id']}: Export-Preset fehlt")
check(len(fx.REGISTRY) >= 31 and len(ids_all["transitions"]) >= 28 and len(ids_all["motions"]) >= 9, "Preset-Anzahl zu klein")
print(f"OK  Presets ({len(fx.REGISTRY)} Effekte, {len(ids_all['transitions'])} Übergänge, {len(ids_all['motions'])} Bewegungen)")

# Workflow und Installer
wf = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
for item in ("--icon", "assets;assets", "THIRD_PARTY.txt", "test_audio.py", "test_motion.py", "test_subtitles.py",
             "test_overlay.py", "test_transitions.py", "test_preview.py", "test_history.py", "ui_smoke.py", "timeline_logic_check.py", "test_diagnostics.py", "SIGN_PFX_BASE64", "requirements-dev.txt", "LASTEXITCODE"):
    check(item in wf, f"build.yml enthält {item} nicht")
tests_dir = {p.name for p in (ROOT / "tests").glob("test_*.py")}
for name in tests_dir:
    check(name in wf or name == "test_release.py", f"{name} läuft nicht im Workflow")
iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
check("SetupIconFile=assets" in iss and "THIRD_PARTY.txt" in iss, "installer.iss ohne Symbol/Lizenzen")
run_lines = [ln for ln in iss.splitlines() if ln.startswith("Filename:") and "MyAppExe" in ln]
check(any("skipifsilent" in ln and "postinstall" in ln for ln in run_lines), "installer.iss: Start-Haken im Dialog fehlt")
check(any("skipifnotsilent" in ln and "postinstall" not in ln for ln in run_lines), "installer.iss: Neustart nach stillem Update fehlt")
check("RestartApplications=no" in iss, "installer.iss: sonst starten bei Updates zwei Programme")
from app.core import updater as _upd  # noqa: E402
_a = _upd.installer_args("C:/x/Setup.exe", "C:/t/u.log")
check(_a[0] == "C:/x/Setup.exe" and "/SILENT" in _a and "/CLOSEAPPLICATIONS" in _a and "/LOG=C:/t/u.log" in _a, _a)
check("/RESTARTAPPLICATIONS" not in _a and "/VERYSILENT" not in _a, "falsche Schalter (VERYSILENT würde den Fortschritt verstecken)")
check(_upd.installer_args("S.exe")[-1] != "/LOG=None", "ohne Protokoll kein /LOG")
check("fonts" in wf and "presets" in wf, "Workflow packt fonts/presets nicht ein")
print("OK  Workflow und Installer")

# Version und Doku
check(re.fullmatch(r"\d+\.\d+\.\d+", version.VERSION) is not None, "VERSION ungültig")
log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
check("SIGN_PFX_BASE64" in (ROOT / "README.md").read_text(encoding="utf-8"), "README erklärt die Signierung nicht")
check(f"## {version.VERSION}" in log, f"CHANGELOG ohne Abschnitt {version.VERSION}")
check((ROOT / "README.md").read_text(encoding="utf-8").startswith("# FATE VIDEOSCHNITT"), "README Kopf")
print(f"OK  Version {version.VERSION} und Doku")

sys.exit(1 if fails else 0)
