"""Gemerkte Oberfläche: Werte prüfen (kaputte werden verworfen), speichern und wieder laden (eigener Ordner, kein Qt)."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp)                       # eigener Einstellungsordner
from app.core import settings  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


N_LANES, N_TABS, MAXZ = 6, 13, 40.0
good = {"ui_locked": [3, 0, 3, 9, -1, True, "x"], "ui_zoom": 12.5, "ui_hsplit": [700, 760], "ui_vsplit": [520, 340], "ui_tab": 5}
c = settings.clean_ui(good, N_LANES, N_TABS, MAXZ)
check(c == {"ui_locked": [0, 3], "ui_zoom": 12.5, "ui_hsplit": [700, 760], "ui_vsplit": [520, 340], "ui_tab": 5}, c)
bad = {"ui_locked": "alle", "ui_zoom": "viel", "ui_hsplit": [1], "ui_vsplit": [0, 0], "ui_tab": 99}
c = settings.clean_ui(bad, N_LANES, N_TABS, MAXZ)
check(c == {"ui_locked": [], "ui_zoom": 1.0, "ui_hsplit": [], "ui_vsplit": [], "ui_tab": 0}, c)
check(settings.clean_ui({"ui_zoom": 9999}, N_LANES, N_TABS, MAXZ)["ui_zoom"] == MAXZ, "Zoom begrenzen")
check(settings.clean_ui({"ui_zoom": -3}, N_LANES, N_TABS, MAXZ)["ui_zoom"] == 1.0, "Zoom nach unten begrenzen")
check(settings.clean_ui({"ui_zoom": float("nan")}, N_LANES, N_TABS, MAXZ)["ui_zoom"] == 1.0, "NaN")
check(settings.clean_ui({"ui_tab": True}, N_LANES, N_TABS, MAXZ)["ui_tab"] == 0, "bool ist kein Reiter")
check(settings.clean_ui({"ui_hsplit": [-5, 100]}, N_LANES, N_TABS, MAXZ)["ui_hsplit"] == [], "negative Größen")
print("OK  Werte prüfen")

# Speichern und Laden; andere Einstellungen bleiben erhalten
settings.save({"preview_len": 15.0})
settings.save(good)
d = settings.load()
check(d["preview_len"] == 15.0 and d["ui_tab"] == 5 and d["ui_zoom"] == 12.5 and d["ui_hsplit"] == [700, 760], d)
check(settings.clean_ui(d, N_LANES, N_TABS, MAXZ)["ui_locked"] == [0, 3], "Rundlauf Sperren")
# kaputte Datei → Standardwerte
settings._file().write_text("{kaputt", encoding="utf-8")
d = settings.load()
check(d["ui_tab"] == 0 and d["ui_locked"] == [] and d["live_preview"] is True, d)
# Datei mit fremden Schlüsseln
settings._file().write_text(json.dumps({"ui_tab": 2, "unbekannt": 1}), encoding="utf-8")
d = settings.load()
check(d["ui_tab"] == 2 and "unbekannt" not in d, d)
print("OK  Speichern/Laden")
print("ALLES OK")
