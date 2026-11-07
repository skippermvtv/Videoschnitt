"""Kurzanleitung (HTML) für das Hilfe-Fenster. Ohne Qt, damit die Tests sie prüfen können."""

SHORTCUTS = [
    ("Strg+O / Strg+S", "Projekt öffnen / speichern"),
    ("Strg+Z / Strg+Y", "Rückgängig / Wiederholen"),
    ("Strg+P", "Vorschau ab Abspielkopf in voller Qualität"),
    ("Strg+I", "Medien importieren"),
    ("Doppelklick auf das Bild", "Vollbild-Vorschau (Esc beendet, Leertaste startet/stoppt)"),
    ("Strg+E", "Exportieren"),
    ("Leertaste", "Abspielen / Pause"),
    ("Entf", "Gewählten Clip, Audioblock oder Bild-in-Bild löschen"),
    ("Strg + Mausrad", "Timeline zoomen"),
]

STEPS = [
    ("1. Importieren", "Im Reiter „Medien“ (oben links) Videos, Bilder und Musik ins Fenster ziehen oder „Importieren“ klicken. "
                       "Doppelklick auf ein Vorschaubild legt die Datei auf die Timeline."),
    ("2. Schneiden", "Clip anklicken, im Player zur Stelle springen und „Am Abspielkopf teilen“. Ränder der Clips ziehen = kürzen, "
                     "Clip ziehen = Reihenfolge ändern. Im Reiter „Clip“ stellst du Tempo, Lautstärke und Übergänge ein."),
    ("3. Format", "Im Reiter „Format“ das Ziel wählen (YouTube, Shorts, TikTok, Reels, Instagram) und die Anpassung "
                  "(Einpassen, Füllen, unscharfer Hintergrund)."),
    ("4. Aussehen", "Reiter „Bild“ (Licht, Kontrast, Farben, Farbräder, Kurven, LUT), „Effekte“ (Glitch, VHS, Neon … – als Blöcke auf der Spur „FX Effekte“) und „Bewegung“ (Zoom, Schwenk, Drehen)."),
    ("5. Text und Untertitel", "Reiter „Text“ (mit Animationen) und „Untertitel“ (von Hand, per SRT-Datei oder automatisch aus Sprache)."),
    ("6. Ton", "„Ton vom Clip trennen“ legt den Ton auf eine eigene Spur. Musik hinzufügen, Ducking und Lautheit im Reiter „Ton“."),
    ("7. Vorschau", "Mit „● Live“ (neben dem Player) sind alle Änderungen – Effekte, Bild, Ton, Text, Bewegung – nach kurzer Zeit direkt im Player zu sehen. „Vorschau ab Abspielkopf“ (Strg+P) rechnet zusätzlich in höherer Qualität."),
    ("8. Exportieren", "„Exportieren …“ speichert ein MP4. Mit der Option „Grafikkarte nutzen“ geht es auf vielen PCs schneller."),
]

TIPS = [
    "Farbe: Im Reiter „Bild“ gibt es seit 1.3 drei Farbräder (Schatten, Mitten, Lichter – ziehen = Farbstich, Doppelklick = zurück), Kurven (Klick = Punkt, Rechtsklick = löschen) und eine LUT (.cube) mit Stärke-Regler.",
    "Greenscreen: Als Bild-in-Bild hinzufügen, im Reiter „Bild-in-Bild“ „Chroma-Key“ einschalten (Grün/Blau oder eigene Farbe) und „Als Vollbild darüberlegen“ wählen. Das Hauptvideo darunter ist der neue Hintergrund.",
    "Effekte: aus der Liste auf die Spur „FX Effekte“ oben in der Timeline ziehen (oder doppelklicken). Block verschieben = anderer Zeitpunkt, Rand ziehen = Länge ändern, Entf = löschen. Es sind beliebig viele Blöcke möglich, auch vom selben Effekt.",
    "Live-Vorschau: Nach einer Änderung rechnet das Programm im Hintergrund einen kurzen Abschnitt (etwa 6 Sekunden) am Abspielkopf neu und zeigt ihn im Player. Beim Abspielen rechnet es den nächsten Abschnitt schon vorab. „● Live“ ausschalten = Player zeigt wieder die Originaldatei.",
    "Masken: Die Effekte der Kategorie „Maske“ (weichzeichnen, verpixeln, hervorheben, schwärzen) wirken nur in einem Bereich. Im Reiter „Effekte“ beim gewählten Block auf „Bereich im Vorschaubild festlegen“ klicken: Rahmen in der Mitte verschieben, an Rändern und Ecken die Größe ziehen. Die Zahlenfelder darunter gehen auch.",
    "Tracking: Rahmen über das Objekt legen und „Objekt verfolgen“ klicken. Der Bereich wandert dann über die Länge des Blocks (höchstens 30 s) mit. Springt er falsch, den Rahmen enger um das Objekt legen oder den Block kürzen. Rahmen verschieben entfernt den Pfad wieder.",
    "Stabilisieren: Im Reiter „Clip“ den Regler „Stabilisieren“ hochziehen. Beim ersten Mal wird der Clip analysiert (Fortschritt neben „● Live“), danach ist es gespeichert. Hohe Werte beruhigen stärker, schneiden aber mehr vom Bildrand ab.",
    "Titel: Im Reiter „Titel“ eine Vorlage doppelklicken (landet am Abspielkopf) oder auf die Timeline ziehen. Danach im Reiter „Text“ Wortlaut, Schrift und Farbe ändern.",
    "Übergänge: Im Reiter „Übergänge“ eine Vorlage doppelklicken (kommt nach dem gewählten Clip) oder auf die Schnittstelle zwischen zwei Clips ziehen. „Auf alle Clips“ setzt ihn überall.",
    "Split Screen: Mehrere Videos als Bild-in-Bild zur selben Zeit auf V2 legen, im Reiter „Split“ ein Layout wählen und „Anwenden“ klicken. Oder in der Medienliste Videos markieren und „Gewählte Medien als Split einfügen“.",
    "Geschwindigkeitskurve: Im Reiter „Clip“ eine Vorlage wählen (z. B. „Zeitlupe in der Mitte“) oder die Kurve zeichnen: Punkte ziehen (senkrecht = Tempo, waagerecht = Stelle im Clip), Doppelklick = neuer Punkt, Rechtsklick = Punkt entfernen. Eintippen geht auch (Position in %:Tempo). „Kurve anwenden“ teilt den Clip in Abschnitte. Strg+Z macht es rückgängig.",
    "Tempokurve ändern: Abschnitt anklicken, die Kurve erscheint wieder; Punkte anpassen und „Kurve ersetzen“. „Kurve entfernen“ macht wieder einen Clip daraus. „Kurve speichern …“ legt eigene Kurven in der Vorlagenliste ab (★).",
    "Nach dem Export zeigt das Programm die Lautheit der fertigen Datei (LUFS), damit du siehst, wie nah sie am Ziel liegt.",
    "Greenscreen im Hauptvideo: Im Reiter „Clip“ unter „Chroma-Key“ einschalten, Farbe wählen (Pipette zeigt ein Bild des Clips) und mit „Hintergrund wählen …“ ein Bild oder Video dahinterlegen; ohne Hintergrund ist es schwarz.",
    "Nach einem Update zeigt das Programm einmal, was sich geändert hat. Das Fenster lässt sich dort abschalten.",
    "Mehrere Formate auf einmal: „Datei → Mehrere Formate exportieren …“ (Strg+Umschalt+E), Formate ankreuzen, Ordner wählen – alle werden nacheinander exportiert.",
    "Pipette: Beim Chroma-Key „Pipette …“ klicken, im Standbild auf den Hintergrund klicken – die Schlüsselfarbe wird übernommen. Split: Abstand, Trennlinie, Bildausschnitt und Hauptvideo im Feld stehen im Reiter „Split“ und bei „Bild-in-Bild“.",
    "Ton von Bild-in-Bild-Videos: im Reiter „Bild-in-Bild“ „Ton mischen“ einschalten. „Lautheit angleichen“ (Reiter „Ton“) hat wählbare Ziele (−14, −16, −23 LUFS).",
    "Ton verbessern: Im Reiter „Clip“ (oder „Ton“ beim Audioblock) den Regler „Rauschen entfernen“ hochziehen, bis das Rauschen leiser ist, ohne dass die Stimme dumpf wird. „Sprache klarer“ schneidet Brummen ab und hebt die Sprachverständlichkeit an.",
    "Das Programm merkt sich beim Beenden Fensteraufteilung, Zoom, gesperrte Spuren und den letzten Reiter.",
    "Timeline: Medien aus dem Reiter „Medien“ direkt auf die Timeline ziehen (landen vor oder hinter dem Clip an der Stelle). Im Spurkopf stellt „M“ eine Tonspur stumm, „S“ sperrt eine Spur gegen versehentliches Verschieben (nur in dieser Sitzung).",
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
