"""Live-Vorschau-Qualität: erlaubte Werte, Standard, Einstellung wird gespeichert."""
import os
import sys
import tempfile
from pathlib import Path

tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "appdata_live")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import preview, settings  # noqa: E402
from app.core.project import Clip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


heights = [h for h, _ in preview.LIVE_QUALITIES]
check(heights == [180, 270, 360, 540, 720] and preview.LIVE_DEFAULT == 360, heights)
check(all(preview.clean_live_height(h) == h for h in heights), "gültige Werte bleiben")
for bad in (None, "abc", 0, 1080, -5, 361, "540x", [], 540.0 - 1):
    check(preview.clean_live_height(bad) == 360, f"ungültig: {bad!r}")
check(preview.clean_live_height("540") == 540 and preview.clean_live_height(720.0) == 720, "Text/Zahl wird umgesetzt")
check(settings.load()["live_height"] == 360, "Standard")
settings.save({"live_height": 540})
check(settings.load()["live_height"] == 540, "gespeichert")

# Andere Höhe ergibt anderen Zwischenspeicher-Schlüssel (sonst käme das alte Bild)
p = Project()
p.clips = [Clip("a.mp4", 10.0, 0.0, 10.0)]
check(preview.key(p, 0.0, 6.0, 360) != preview.key(p, 0.0, 6.0, 540), "Schlüssel hängt von der Höhe ab")
print("ALLES OK")
