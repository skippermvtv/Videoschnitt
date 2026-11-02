"""Kurzanleitung (HTML) für das Hilfe-Fenster. Ohne Qt, damit die Tests sie prüfen können."""

SHORTCUTS = [
    ("Strg+O / Strg+S", "Projekt öffnen / speichern"),
    ("Strg+Z / Strg+Y", "Rückgängig / Wiederholen"),
    ("Strg+P", "Vorschau ab Abspielkopf"),
    ("Strg+E", "Exportieren"),
    ("Leertaste", "Abspielen / Pause"),
    ("Entf", "Gewählten Clip, Audioblock oder Bild-in-Bild löschen"),
    ("Strg + Mausrad", "Timeline zoomen"),
]

STEPS = [
    ("1. Importieren", "Videos, Bilder und Musik ins Fenster ziehen oder „Dateien importieren“ klicken. "
                       "Doppelklick legt eine Datei auf die Timeline."),
    ("2. Schneiden", "Clip anklicken, im Player zur Stelle springen und „Am Abspielkopf teilen“. Ränder der Clips ziehen = kürzen, "
                     "Clip ziehen = Reihenfolge ändern. Im Reiter „Clip“ stellst du Tempo, Lautstärke und Übergänge ein."),
    ("3. Format", "Im Reiter „Format“ das Ziel wählen (YouTube, Shorts, TikTok, Reels, Instagram) und die Anpassung "
                  "(Einpassen, Füllen, unscharfer Hintergrund)."),
    ("4. Aussehen", "Reiter „Bild“ (Licht, Kontrast, Farben, Farbräder, Kurven, LUT), „Effekte“ (Glitch, VHS, Neon … – als Blöcke auf der Spur „FX Effekte“) und „Bewegung“ (Zoom, Schwenk, Drehen)."),
    ("5. Text und Untertitel", "Reiter „Text“ (mit Animationen) und „Untertitel“ (von Hand, per SRT-Datei oder automatisch aus Sprache)."),
    ("6. Ton", "„Ton vom Clip trennen“ legt den Ton auf eine eigene Spur. Musik hinzufügen, Ducking und Lautheit im Reiter „Ton“."),
    ("7. Vorschau", "„Vorschau ab Abspielkopf“ (Strg+P) zeigt das Ergebnis mit allen Effekten in kleiner Auflösung."),
    ("8. Exportieren", "„Exportieren …“ speichert ein MP4. Mit der Option „Grafikkarte nutzen“ geht es auf vielen PCs schneller."),
]

TIPS = [
    "Farbe: Im Reiter „Bild“ gibt es seit 1.3 drei Farbräder (Schatten, Mitten, Lichter – ziehen = Farbstich, Doppelklick = zurück), Kurven (Klick = Punkt, Rechtsklick = löschen) und eine LUT (.cube) mit Stärke-Regler.",
    "Greenscreen: Als Bild-in-Bild hinzufügen, im Reiter „Bild-in-Bild“ „Chroma-Key“ einschalten (Grün/Blau oder eigene Farbe) und „Als Vollbild darüberlegen“ wählen. Das Hauptvideo darunter ist der neue Hintergrund.",
    "Effekte: aus der Liste auf die Spur „FX Effekte“ oben in der Timeline ziehen (oder doppelklicken). Block verschieben = anderer Zeitpunkt, Rand ziehen = Länge ändern, Entf = löschen. Es sind beliebig viele Blöcke möglich, auch vom selben Effekt.",
    "Die Vorschau im Player zeigt die Originaldatei ohne Effekte – die fertige Wirkung siehst du in „Vorschau ab Abspielkopf“.",
    "Eigene Schriften: Reiter „Text“ → „Schrift hinzufügen …“. Fehlen Zeichen in der Schrift, warnt das Programm vor dem Export.",
    "Eigene Presets (Formate, Looks, Übergänge, Bewegungen) lassen sich ohne neues Update ergänzen: Menü „Hilfe → Eigene Presets-Ordner öffnen“.",
    "Das Programm sichert alle 30 Sekunden automatisch. Nach einem Absturz fragt es beim Start, ob es die Arbeit wiederherstellen soll.",
    "Fehlen Dateien (verschoben oder umbenannt), hilft „Bearbeiten → Fehlende Dateien suchen …“.",
    "Updates: „Hilfe → Nach Updates suchen“ – neue Versionen werden aus dem GitHub-Release geladen.",
]


def help_html() -> str:
    rows = "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in SHORTCUTS)
    steps = "".join(f"<p><b>{t}</b><br>{d}</p>" for t, d in STEPS)
    tips = "".join(f"<li>{t}</li>" for t in TIPS)
    return (f"<h2>Kurzanleitung</h2>{steps}<h3>Tastenkürzel</h3><table cellpadding='4'>{rows}</table>"
            f"<h3>Tipps</h3><ul>{tips}</ul>")
