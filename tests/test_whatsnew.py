"""„Was ist neu“: Versionsvergleich und Aufbereitung der CHANGELOG (reine Logik, ohne Qt)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import whatsnew as wn  # noqa: E402
from app import version  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FEHLER:", msg)
        sys.exit(1)


LOG = """# Änderungen

## 1.4.4
- **Neu**: Fenster <b>nach</b> Update, `Code`
Zweite Zeile ohne Punkt.

## 1.4.3
- Neustart
- Lautheit

## 1.4.2
- Titel

## 1.4.1
- Masken

## 1.4.0
- Oberfläche

## 1.3.0
- Farbe
"""
check(wn.parse_version("1.4.3") == (1, 4, 3) and wn.parse_version("v2.0.10") == (2, 0, 10), "parse_version")
check(wn.parse_version("1.4") is None and wn.parse_version("") is None and wn.parse_version(None) is None and wn.parse_version("1.4.x") is None, "parse_version ungültig")
check(wn.parse_version("1.10.0") > wn.parse_version("1.9.0"), "Zahlen- statt Textvergleich")
s = wn.sections(LOG)
check(list(s)[0] == (1, 4, 4) and s[(1, 4, 3)] == "- Neustart\n- Lautheit" and len(s) == 6, f"sections: {list(s)}")
print("OK  Versionen und Abschnitte")

d = wn.decide("1.4.3", "1.4.4", True, LOG)
check([v for v, _ in d] == ["1.4.4"], f"Update um eine Version: {d}")
d = wn.decide("1.4.0", "1.4.4", True, LOG)
check([v for v, _ in d] == ["1.4.4", "1.4.3", "1.4.2", "1.4.1"], f"übersprungene Versionen, auf {wn.MAX_SECTIONS} begrenzt: {d}")
check(wn.decide("1.4.4", "1.4.4", True, LOG) == [], "gleiche Version: nichts")
check(wn.decide("1.4.5", "1.4.4", True, LOG) == [], "Rückschritt: nichts")
check(wn.decide("", "1.4.4", False, LOG) == [], "Erstinstallation: nichts")
check([v for v, _ in wn.decide("", "1.4.4", True, LOG)] == ["1.4.4"], "Update von einer Version ohne gemerkten Stand: nur die aktuelle")
check(wn.decide("garbage", "1.4.4", False, LOG) == [], "kaputter Stand ohne Einstellungen")
check(wn.decide("1.4.3", "kaputt", True, LOG) == [], "kaputte aktuelle Version")
check(wn.decide("1.4.3", "1.4.4", True, "") == [] and wn.decide("1.4.3", "1.4.4", True, None) == [], "CHANGELOG fehlt")
check(wn.decide("1.4.3", "1.4.4", True, "# x\n## 1.4.3\n- a") == [], "Abschnitt der neuen Version fehlt")
print("OK  Entscheidung")

h = wn.to_html(wn.decide("1.4.3", "1.4.4", True, LOG))
check("<h3>Version 1.4.4</h3>" in h and "<ul>" in h and "<li><b>Neu</b>:" in h and "<code>Code</code>" in h, h)
check("&lt;b&gt;nach&lt;/b&gt;" in h and "<b>nach</b>" not in h, "HTML aus der CHANGELOG muss maskiert werden")
check("<p>Zweite Zeile ohne Punkt.</p>" in h and h.count("<ul>") == 1 and h.count("</ul>") == 1, h)
print("OK  HTML")

# die echte CHANGELOG: aktuelle Version hat einen Abschnitt mit Inhalt
real = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
cur = wn.decide("0.0.1", version.VERSION, True, real)
check(cur and cur[0][0] == version.VERSION and len(cur[0][1]) > 20, f"echte CHANGELOG: {version.VERSION}")
print("OK  echte CHANGELOG")
print("ALLES OK")
