# Änderungen

## 1.4.6
- **Gleichzeitige Bild-in-Bild-Blöcke in eigenen Zeilen**: Blöcke, die zur gleichen Zeit laufen (z. B. beim Split Screen oder bei mehreren Bild-in-Bild-Videos übereinander), liegen in der Timeline jetzt in bis zu drei Zeilen untereinander und verdecken sich nicht mehr; die Spur wird dann höher. Ein einzelner Block sieht aus wie bisher. Der Export konnte schon immer mehrere Blöcke gleichzeitig; neu ist die Anzeige und die Auswahl per Klick.
- **Chroma-Key-Vorschau** (Reiter „Clip“, Knopf „Vorschau …“): zeigt ein Bild aus der Mitte des Clips mit Key und Hintergrund, so wie der Export es rechnet (auch für Standbilder). Der Clip selbst bleibt dabei unverändert.
- Neue Tests: `test_overlay_rows.py`, `test_key_preview.py`; erweiterte Timeline-, Signal- und Oberflächenprüfungen.

## 1.4.5
- **Lautheit nach dem Export gemessen**: Nach jedem Export zeigt das Programm die tatsächliche Lautheit der fertigen Datei an, z. B. „Lautheit: −13,2 LUFS (Ziel −14,0)“ (Statuszeile und Abschlussfenster; bei „Mehrere Formate“ einmal). Gemessen wird die Datei selbst (EBU R128), nicht geschätzt. Das Angleichen bleibt ein Durchgang und landet etwa 1 LU über dem Ziel; jetzt siehst du es.
- **Eigene Tempokurven speichern**: Im Reiter „Clip“ die Kurve mit „Kurve speichern …“ unter einem Namen sichern. Sie erscheint in der Vorlagenliste mit ★ (bis zu 20, gleicher Name ersetzt), „Gespeicherte löschen“ entfernt sie.
- **Tempokurve nachträglich ändern**: Die Abschnitte einer angewendeten Kurve merken sich Kurve, Grundtempo und Bewegung. Klickst du einen Abschnitt an, erscheint die Kurve wieder im Editor; „Kurve ersetzen“ berechnet die Abschnitte neu, „Kurve entfernen“ führt sie wieder zu einem Clip zusammen (Anfang, Ende, Tempo, Übergang und Bewegung wie vorher). Wurde ein Abschnitt verschoben, gekürzt oder gelöscht, erkennt das Programm das und behandelt den Abschnitt wie einen normalen Clip.
- **Prüfungen**: Der Oberflächentest bricht nicht mehr beim ersten Fehler ab, sondern läuft alle Abschnitte durch und meldet am Ende alle Fehler zusammen (spart Durchläufe auf dem Build-Server). Neue Tests: `test_loudcheck.py`, `test_ramp_reapply.py`; erweiterte Tests für eigene Kurven.

## 1.4.4
- **„Was ist neu“-Fenster**: Nach einem Update (neue Version beim Start) zeigt das Programm einmal die Änderungen der neuen Version, bei übersprungenen Versionen bis zu vier Abschnitte. Es erscheint nicht bei der Erstinstallation und nicht bei einem Rückschritt auf eine ältere Version; mit „Nicht mehr anzeigen“ lässt es sich abschalten. Der Text kommt aus der CHANGELOG, die jetzt im Programm mitgeliefert wird (`--add-data` in `build.bat` und im Workflow).
- **Chroma-Key auf dem Hauptvideo** (Reiter „Clip“): Greenscreen-Clip der Hauptspur, Farbe (Grün, Blau, eigene Farbe, Pipette), Toleranz, weiche Kante, Farbsaum. Dahinter scheint ein Hintergrund durch: ein Bild, ein Video (läuft in Schleife) oder Schwarz. Gilt pro Clip und wird beim Teilen (z. B. Tempokurve) mit vererbt. Pixeltest über Bild, Video und Schwarz.
- **Fehler behoben (Ton, Tempokurve):** An den Grenzen der Abschnitte knackte der Ton, weil `atempo` in jedem Stück neu beginnt. Jetzt werden an solchen Schnittstellen 4 ms aus- und eingeblendet. Gemessen: größter Sprung im Signal gleich wie beim unveränderten Sinuston (vorher 0,25 gegen 0,008).
- **Fehler behoben (Export unter Windows, vom Build-Server gefunden):** Bei vielen Abschnitten (Tempokurve auf mehreren Clips, Übergänge, Bewegung) wurde der FFmpeg-Befehl länger als Windows erlaubt (`WinError 206: The filename or extension is too long`, Grenze ca. 32 000 Zeichen) und der Export brach ab. Lange Filtergraphen (über 8000 Zeichen) werden jetzt in eine Datei geschrieben (`-/filter_complex` bzw. `-filter_complex_script`, je nach FFmpeg-Version einmal ausprobiert). Neuer Test mit 40 Abschnitten.
- README: „Bekannte Grenzen“ auf den Stand 1.4.3/1.4.4 gebracht.
- Nicht umgesetzt: Lautheit in zwei Durchgängen (Bild und Ton hängen im Export in einem Filtergraph, ein reiner Mess-Durchlauf lässt sich nicht sauber abtrennen; Gewinn nur etwa 1 LU).
- Neue Tests: `test_whatsnew.py`, `test_key_main.py`; `test_ramp_audio.py` prüft jetzt auch das Knacken; erweiterte Signal-, Oberflächen- und Release-Prüfungen.

## 1.4.3
- **Neustart nach dem Update**: Nach „Jetzt installieren“ startet das Programm von selbst wieder (Inno-Setup-Eintrag für den stillen Modus). Vorher fragt das Programm, ob ungespeicherte Änderungen gesichert werden sollen. Das Installationsprotokoll liegt in `%TEMP%\FATE-VIDEOSCHNITT-Update.log`. Ob der Neustart klappt, zeigt sich erst beim ersten echten Update (1.4.2 → 1.4.3) auf Windows.
- **Lautheit angleichen** (Reiter „Ton“): Ziel wählbar (−14 LUFS YouTube/TikTok, −16, −23 Sendenorm). Gemessen mit echtem Export; der Ein-Durchgang-Filter landet etwa 1 LU über dem Ziel (Toleranz im Test 1,5 LU).
- **Musik-Ducking** (Musik wird bei Sprache leiser): Zuordnung der Stärke zum Verhältnis neu abgestimmt und gemessen. Ton von Bild-in-Bild-Videos zählt dabei zur Sprache.
- **Ton von Bild-in-Bild**: Schalter „Ton mischen“ und Lautstärke (0–200 %) im Reiter „Bild-in-Bild“.
- **Mehrere Formate auf einmal exportieren** (Datei → „Mehrere Formate exportieren …“, Strg+Umschalt+E): z. B. YouTube 16:9, Shorts und Quadrat nacheinander in einen Ordner.
- **Split Screen**: Abstand und Trennlinie (Farbe) zwischen den Feldern, Bildausschnitt pro Feld (Zoom und Verschiebung), und das Hauptvideo kann selbst in ein Feld (erstes oder letztes) rücken, solange der Split läuft.
- **Pipette** für Greenscreen: „Pipette …“ zeigt ein Standbild, ein Klick wählt die Schlüsselfarbe (Mittelwert um den Klickpunkt).
- **Geschwindigkeitskurve zeichnen**: Grafik im Reiter „Clip“ (Tempo senkrecht auf logarithmischer Achse ×0,1 … ×8). Punkte ziehen, Doppelklick = neuer Punkt, Rechtsklick = Punkt entfernen; das Textfeld und die Vorlagen bleiben in Sync.
- **Fehler behoben (Ton in der Geschwindigkeitskurve):** Bei langsamem Tempo liefert FFmpegs `atempo` bis ca. 50 ms zu wenig Ton; `concat` füllte die Lücke mit Stille, an den Abschnittsgrenzen gab es hörbare Aussetzer (gemessen bis 44 ms). Jetzt wird etwas mehr Ton gelesen und exakt auf die Bildlänge gekürzt. Ein leichtes Knacken durch den Phasensprung an den Grenzen bleibt möglich.
- Neue Tests: `test_loudness.py`, `test_overlay_audio.py`, `test_multiexport.py`, `test_colorpick.py`, `test_ramp_audio.py`, `test_rampgraph.py`; erweiterte Split-, Release-, Signal- und Oberflächenprüfungen.

## 1.4.2
- **Reiter „Titel“**: 11 Vorlagen (Großer Titel, Titel mit Kasten, Bauchbinde, Untertitelband, Zitat, Kapitel, Schreibmaschine, Ausruf, Abonnieren, Abspann, Metal). Doppelklick legt den Titel am Abspielkopf an, oder die Vorlage auf die Timeline ziehen. Danach lässt er sich im Reiter „Text“ wie jeder Text ändern. Vorlagen stehen in `presets/titles.json` und lassen sich im Presets-Ordner ergänzen.
- **Reiter „Übergänge“**: Raster mit Vorschaubildern (echte kurze Überblendung zwischen zwei Testbildern, zwischengespeichert). Doppelklick = Übergang nach dem gewählten Clip, auf eine Schnittstelle ziehen, „Auf alle Clips“, „Entfernen“, Dauer einstellbar. Die Reiterleiste scrollt jetzt, wenn sie breiter als das Fenster ist.
- **Split Screen** (Reiter „Split“): 2 nebeneinander, 2 übereinander, 1 groß + 2 klein, 3 nebeneinander, 4er-Raster. Der gewählte Bild-in-Bild-Block und die gleichzeitig laufenden bekommen je ein Feld; jedes Video füllt sein Feld aus. „Gewählte Medien als Split einfügen“ legt markierte Medien gleich ins Layout. Felder schließen lückenlos aneinander an (Pixeltest in 3 Bildgrößen).
- **Geschwindigkeitskurve** (Reiter „Clip“): Vorlagen (Zeitlupe in der Mitte, Immer schneller, Abbremsen, Heldenmoment, Pulsieren, Blitzstart) oder eigene Punkte („Position in %:Tempo“). Der Clip wird in bis zu 20 Abschnitte mit gleichbleibender Geschwindigkeit geteilt; Timeline, Übergänge, Live-Vorschau und Ton laufen dadurch unverändert mit. Nicht für Standbilder und rückwärts abgespielte Clips. Rückgängig mit Strg+Z.
- **Ton verbessern** (Reiter „Clip“ und „Ton“): „Rauschen entfernen“ (afftdn) und „Sprache klarer“ (Tiefen abschneiden, 3 kHz anheben), je 0–100. afftdn wirkt nur, wenn man ihm den ungefähren Rauschpegel nennt; der wird deshalb pro Datei gemessen (leiseste 10 % kurzer Stücke) und zwischengespeichert.
- **Einstellungen merken**: Spursperren, Timeline-Zoom, Fensteraufteilung und der zuletzt benutzte Reiter werden beim Beenden gespeichert und beim Start wiederhergestellt (kaputte Werte werden verworfen).
- **Fehler behoben (Export):** Bei vielen Schnitten wurde das Video mit jedem Schnitt etwas länger als der Ton (jeder Clip rundete auf ganze Quellbilder auf; bei 19 Abschnitten +0,4 s, Bild und Ton liefen auseinander). Die Bildanzahl je Clip wird jetzt laufend gerundet.
- Neue Tests: `test_titles.py`, `test_settings_ui.py`, `test_audiofix.py` (verrauschter Ton, gemessen), `test_split.py` (Pixeltest), `test_speedramp.py` (Helligkeit = Quellzeit, Länge, Ton); erweiterte Signal-, Timeline- und Oberflächenprüfungen.

## 1.4.1
- **Masken direkt im Vorschaubild**: Im Reiter „Effekte“ zeigt „Bereich im Vorschaubild festlegen“ ein Bild an der Stelle des Abspielkopfs (ohne Effekte). Den Rahmen in der Mitte verschieben, an Rändern und Ecken in der Größe ziehen; die Zahlenfelder folgen mit.
- **Tracking**: „Objekt verfolgen“ lässt den Maskenbereich über die Länge des Blocks (höchstens 30 s) mit einem Objekt mitwandern (Mustersuche per Kreuzkorrelation auf kleinen Graustufenbildern, Pfad geglättet und auf höchstens 40 Punkte vereinfacht). Das Programm enthält dafür jetzt numpy.
- **Videostabilisierung**: Regler „Stabilisieren“ (0–100) im Reiter „Clip“. Zwei Durchgänge mit vidstab; die Analyse läuft im Hintergrund und wird gespeichert. Für die Live-Vorschau wird der passende Ausschnitt aus der Analyse geschnitten, statt neu zu rechnen. Neuere FFmpeg-Versionen (z. B. das im Installer) schreiben die Analyse im Binärformat, dann wird jeder Ausschnitt einzeln analysiert. Die Glättung läuft mit `optalgo=gauss`, weil die Standard-Optimierung neuerer libvidstab-Versionen mit festem Zoom zu schwach ausgleicht (vom Build-Server gefunden). Ohne vidstab im FFmpeg greift die einfachere Variante `deshake`.
- **Oberfläche**: Medien aus dem Raster auf die Timeline ziehen (mit Einfügemarke), Spurköpfe mit „M“ (Tonspur stumm) und „S“ (Spur sperren, nur in der Sitzung), Vollbild-Vorschau (Knopf oder Doppelklick, Esc beendet), Zoomregler folgt Strg+Mausrad.
- **Robuster beim Start**: Player und Timeline werden vor den Reitern gebaut (wie vor 1.4.0), damit Felder, die beim Aufbau Slots auslösen, nichts Fehlendes antreffen.
- Neue Tests: `test_mask_edit.py` (Rahmen-Geometrie, Einzelbild ohne Effekt), `test_tracker.py` (bewegtes Objekt auf Rauschen, Abweichung unter 3 %), `test_stabilize.py` (verwackeltes Video vor/nach, Ausschnitte, Zwischenspeicher), erweiterte Fenster- und Timeline-Prüfungen.

## 1.4.0
- **Neue Oberfläche** nach dem Vorbild gängiger Schnittprogramme: Reiterleiste oben links (Medien, Format, Bild, Effekte, Text, Clip, Ton, Bild-in-Bild, Untertitel, Bewegung) mit **EXPORT**-Knopf, große Vorschau oben rechts, Timeline unten mit Werkzeugleiste (Rückgängig, Wiederholen, Löschen, Teilen, Verschieben, Ton trennen, Musik und Bild-in-Bild hinzufügen, Zoomregler, „Alles“).
  - Neuer Reiter **Medien**: Raster mit Vorschaubildern, Suchfeld, „Importieren“; Doppelklick legt auf die Timeline. Vorschaubilder werden im Hintergrund erzeugt und zwischengespeichert.
  - Vorschau mit **Zeitcode**, Suchleiste über die ganze Projektlänge (Klick springt), Knöpfe Anfang / Abspielen / Ende.
  - Dunkles Design mit türkisen Akzenten; der Name steht rot oben rechts in der Menüleiste. Neues Menü „Datei“.
- **Live-Vorschau**: Änderungen an Effekten, Bild, Ton, Text, Bewegung usw. sind nach kurzer Zeit direkt im Player zu sehen, ohne „Vorschau ab Abspielkopf“. Ein kurzer Abschnitt am Abspielkopf wird im Hintergrund neu gerechnet, beim Abspielen schon der nächste vorab. Ausschaltbar mit „● Live“. Die alte Vorschau (Strg+P) bleibt für höhere Qualität.
- **Masken-Effekte** (Bereich weichzeichnen, verpixeln, hervorheben, schwärzen): Form, Mitte, Größe und weiche Kante im Reiter „Effekte“. Mitwandern mit einem Objekt (Tracking) und Videostabilisierung folgen noch.
- **Fehler behoben (Export):** Übergang → harter Schnitt → Übergang brach mit „timebase do not match“ ab. Nach dem harten Schnitt wird jetzt die Bildrate angeglichen.
- Neue Tests: Zeitfenster-Projekt (`test_window.py`), Masken (`test_masks.py`), erweiterte Oberflächen-Prüfungen für Live-Vorschau, Medienraster und Maskenfelder.

## 1.3.0
- **Farbräder** (Schatten, Mitten, Lichter) im Reiter „Bild“: ziehen = Farbstich, Doppelklick = zurücksetzen.
- **Kurven-Editor** für Helligkeit, Rot, Grün und Blau (bis 12 Punkte). Die gezeichnete Kurve entspricht dem Ergebnis von FFmpeg.
- **LUT-Import** (`.cube` 3D/1D, `.3dl`) mit Stärke-Regler. Die Datei wird in den Datenordner kopiert, wird sie gelöscht, meldet es „Fehlende Dateien suchen“. Unvollständige oder falsche LUTs werden beim Laden abgelehnt.
- **Chroma-Key (Greenscreen)** für Bild-in-Bild: Grün, Blau oder eigene Farbe, Toleranz, weiche Kante, Farbsaum entfernen, „Als Vollbild darüberlegen“.
- 4 neue Bild-Voreinstellungen: Teal & Orange, S-Kurve, Verblasster Film, Cyber.
- Alte Projekte laden unverändert; neue Felder haben neutrale Standardwerte.
- Neue Tests: `test_color13.py` (Pixelprüfung mit echtem FFmpeg, LUT-Pfade mit Sonderzeichen, Greenscreen), `test_color13_logic.py` (Farbrad, Kurvenpunkte, Spline gegen FFmpeg), erweiterte Fenster-Tests.
- Noch nicht in 1.3.0: Masken, Tracking, Videostabilisierung (kommen in 1.3.1).

## 1.2.1
- Zweite Fehlersuche nach 1.2.0:
  - Tests rufen FFmpeg jetzt über das mitgelieferte Programm auf (vorher über den Namen `ffmpeg`, was auf dem Build-Server rot geworden wäre).
  - Die Effektliste kopiert beim Ziehen auf die Effekt-Spur, statt den Eintrag zu verschieben.
  - `ui_logic_check` läuft jetzt auch im Build-Workflow.
  - Zufalls-Härtetest der Effekt-Blöcke (Modell und echter Export mit sehr kurzen, überlappenden und überstehenden Blöcken): keine Fehler.

## 1.2.0
- **Neuer Name: FATE VIDEOSCHNITT** (vorher ClipForge) – Fenster, Installer (`FATE-VIDEOSCHNITT-Setup.exe`), Programmdatei, Hilfe, Lizenzen und README.
  - Der Datenordner `%APPDATA%\ClipForge` wird beim ersten Start automatisch in `%APPDATA%\FATE VIDEOSCHNITT` umbenannt (Einstellungen, Presets, Schriften, Autosave, Spracherkennung bleiben erhalten).
  - Die Schrift heißt jetzt „FATE Metal“ (`FateMetal.ttf`); Projekte, die noch die alte Schrift nennen, finden sie automatisch.
  - Das Setup ersetzt eine vorhandene ClipForge-Installation und entfernt die alte `ClipForge.exe` samt Verknüpfungen. Projektdateien (`.cforge`) bleiben kompatibel.
- **Neue Spur „FX Effekte“** ganz oben in der Timeline: Effekte sind jetzt Blöcke mit Zeitfenster.
  - Aus der Effektliste in die Spur ziehen (oder doppelklicken / „＋ Auf Effekt-Spur“), verschieben (rastet ein), Rand ziehen für die Länge, Entf zum Löschen.
  - Beliebig viele Blöcke, auch vom selben Effekt; überlappende Blöcke liegen untereinander.
  - Der Reiter „Effekte“ ändert Stärke, Anfang und Ende des gewählten Blocks. Alte Projekte laden unverändert.
- Neue Tests: Effekt-Spur (Modell, Export mit echtem FFmpeg, Maus-Logik, Ablegen), Umbenennung und Datenordner-Umzug.

## 1.1.4
- **Fehler behoben:** Beim Start des Fensters lösten die Felder „Geschwindigkeit“ (Ton und Bild-in-Bild) einen Fehler aus, weil Regler daneben noch nicht existierten. Das war der erste Fund aus dem echten Qt-Start auf dem Build-Server.
- Der Oberflächen-Test macht Fehler in Qt-Slots jetzt zu Testfehlern (Qt gibt sie sonst nur aus) und nutzt ein Testvideo mit Ton.

## 1.1.3
- Test-Korrektur: Die Attrappe für die Spracherkennung im Untertitel-Test läuft jetzt auch unter Windows (bisher nur Linux). Das Programm selbst ist unverändert.

## 1.1.2
- Test-Korrektur: Eine Textausgabe mit Pfeil-Zeichen ließ sich in der Windows-Konsole des Build-Servers nicht ausgeben und brach den Lauf ab. Der Workflow nutzt jetzt durchgehend UTF-8 (`PYTHONUTF8`).
- Der Test „Grafikkarte nutzen“ lief bereits durch; auf dem Build-Server wird dabei die CPU genutzt (keine Grafikkarte vorhanden).

## 1.1.1
- **Wichtige Korrektur:** Das Qt-Zusatzpaket `PySide6-Addons` fehlte in `requirements.txt`. Ohne es startet das Programm nicht (Fehler „No module named PySide6.QtMultimedia“). Jetzt enthalten.
- Der Test-Lauf auf GitHub installiert numpy und Pillow (neue Datei `requirements-dev.txt`) und bricht beim ersten fehlgeschlagenen Test sofort ab, mit dem Namen des Tests. Bisher wurden Fehler mittendrin übersehen.
- Neue Prüfung: Jedes importierte Qt-Modul muss in den Paketen aus `requirements.txt` enthalten sein.

## 1.1.0 – Stabilisierung
- **Fehlerprotokoll:** ClipForge schreibt ein Protokoll nach `%APPDATA%\ClipForge\logs` (Start, Exporte, Fehler; rotierend, bleibt klein). Harte Abstürze landen in `crash.txt`.
- **Unerwartete Fehler** zeigen jetzt einen Dialog mit „Bericht kopieren“, statt still zu verschwinden. Das Programm läuft weiter.
- **Hilfe → Diagnose und Fehlerbericht:** testet FFmpeg und alle Encoder (CPU, NVIDIA, Intel, AMD) mit einem Kurztest und zeigt Version, System und Protokollende. Ein Klick kopiert alles zum Weitergeben. Es enthalten keine Projektinhalte.
- **Spracherkennung einrichten:** whisper.cpp und das Sprachmodell (tiny/base/small) werden per Klick heruntergeladen – mit Fortschritt, Abbrechen und Prüfung der Dateigröße. „Untertitel automatisch erzeugen“ startet die Einrichtung selbst, wenn etwas fehlt. Der manuelle Weg bleibt möglich.
- Hilfe → Protokoll-Ordner öffnen.
- Der Workflow signiert die Setup.exe automatisch, sobald die Geheimnisse `SIGN_PFX_BASE64` und `SIGN_PFX_PASSWORD` im Repository hinterlegt sind (siehe README). Ohne Zertifikat läuft alles wie bisher.

## 1.0.0
- **Programmsymbol:** ClipForge hat jetzt ein eigenes Symbol (Fenster, Taskleiste, Verknüpfungen, Installer, Über-Fenster).
- **Hilfe:** Kurzanleitung mit Arbeitsablauf, Tastenkürzeln und Tipps (Hilfe → Kurzanleitung, F1) sowie Lizenzfenster (Hilfe → Lizenzen und Drittanbieter-Software).
- Lizenzhinweise vervollständigt (FFmpeg, Qt/PySide6, fontTools, optional whisper.cpp, Schrift, Symbol).
- Neue Release-Prüfung im Workflow: Symbol, Hilfe, Lizenzen, Presets, Installer und Tests werden vor jedem Build kontrolliert.
- Alle Funktionen aus 0.1–0.9: Presets für YouTube/Shorts/TikTok/Reels, Effekte, Bildkorrektur, Tonspuren, Übergänge, Bild-in-Bild, Untertitel,
  Textanimationen, Keyframe-Bewegung, Rückgängig, Autosave, Vorschau mit Zwischenspeicher, Grafikkarten-Export, Update-Check.

## 0.9.0
- **Neu: „Vorschau ab Abspielkopf“** (Strg+P): rechnet Effekte, Text, Untertitel, Bild-in-Bild, Übergänge, Bewegung und Ton in kleiner Auflösung und spielt das Ergebnis ab; der Abspielkopf in der Timeline läuft mit.
  - Länge wählbar (8 s, 20 s, 1 Minute, bis zum Ende) und Qualität (240p bis 720p)
  - **Zwischenspeicher:** Unveränderte Vorschauen starten sofort; jede Änderung am Projekt oder an einer Quelldatei rechnet neu. Alte Vorschauen werden automatisch aufgeräumt.
- **Neu: Grafikkarte beim Export nutzen** (NVIDIA, Intel, AMD – wird automatisch erkannt). Macht die Grafikkarte Probleme, wiederholt das Programm den Export selbst mit dem Prozessor.
- **Restzeit** im Fortschrittsfenster.
- **Schutz:** „Rückwärts abspielen“ ist nur für Clips bis 90 Sekunden möglich (sonst läuft der Speicher voll) – mit verständlicher Meldung.
- Einstellungen zu Vorschau und Grafikkarte werden gemerkt (`settings.json` in `%APPDATA%\ClipForge`).

## 0.8.0
- **Neu: Registerkarte „Bewegung“** pro Clip:
  - **Drehen** in 90°-Schritten, **Spiegeln** waagerecht/senkrecht, **Zuschneiden** (links/rechts/oben/unten in %)
  - **Keyframes:** Zoom, Schwenk und Drehung ändern sich über die Zeit (bis 12 Keyframes, sanfte Übergänge)
  - 9 Voreinstellungen: Langsam hinein-/herauszoomen, Schwenk links/rechts, Neigen, Ken Burns, Punch-In, Handkamera, Eindrehen
  - „Auf alle Clips anwenden“; Timeline-Markierung „⤢ Bewegung“ und „⟲ Transform“
- **9 neue Effekte:** Posterisieren, Duotone, Nachtsicht, Regenbogen-Farbwechsel, Comic-Kontur, Traum-Glühen, Nachzieh-Spur, Fischauge, Schiefe Kamera.
- 4 neue Looks: Comic, Nachtsicht, Traum, Synthwave.
- Eigene Bewegungen: `motions.json` in `%APPDATA%\ClipForge\presets` (gleicher Aufbau wie `presets/motions.json`).

## 0.7.0
- **Neu: Untertitel** (Registerkarte „Untertitel“): Einträge von Hand anlegen und bearbeiten, **SRT importieren/speichern**, gemeinsamer Stil (Schrift, Größe, Position, Farbe, dunkler Kasten, Animation). Die Untertitel werden ins Video eingebrannt.
- **Neu: automatische Untertitel aus Sprache** mit dem kostenlosen whisper.cpp (läuft lokal auf dem PC). Einmalige Einrichtung, siehe README.
- **Neu: 8 Textanimationen** für Texte: Einblenden/Ausblenden, von unten/rechts hereinfahren, Hüpfen, Schreibmaschine, Wackeln, Blinken; dazu ein dunkler Kasten hinter dem Text.
- Projekte aus älteren Versionen lassen sich weiter öffnen.

## 0.6.0
- **Neu: Standbilder** (JPG, PNG, WebP, BMP, TIFF) als Clips – Standardlänge 5 s, Dauer frei einstellbar (Registerkarte „Clip“, „Ende im Clip“). Bilder haben keinen Ton.
- **Neu: Bild-in-Bild (Spur V2)** über dem Hauptvideo: Videos oder Bilder als Reaktionsvideo, Logo oder Sticker.
  - Registerkarte „Bild-in-Bild“: Start, Von/Bis, Geschwindigkeit, Position (Ecken oder frei), Größe, Deckkraft, Ein-/Ausblenden, Rahmen
  - Block in der Timeline verschieben und an den Rändern kürzen (rastet an Clipgrenzen ein)
  - Ein längeres Overlay verlängert das Video nicht
- Zu sehen in „Vorschau mit Effekten“ und im Export; der Player zeigt nur die Quelldatei.

## 0.5.0
- **Neu: Rückgängig / Wiederholen** (Strg+Z, Strg+Y bzw. Strg+Umschalt+Z, auch in der Werkzeugleiste und im Menü „Bearbeiten“). Reglerbewegungen zählen als ein Schritt.
- **Neu: automatisches Speichern** alle 30 Sekunden; nach einem Absturz bietet das Programm beim Start die Wiederherstellung an.
- Beim Schließen wird bei ungespeicherten Änderungen nachgefragt; der Fenstertitel zeigt „*“.
- **Fehlende Dateien** (beim Öffnen eines Projekts oder über „Bearbeiten → Fehlende Dateien suchen …“) werden in einem gewählten Ordner samt Unterordnern wiedergefunden.
- **Timeline:** Videoclips mit der Maus kürzen (Rand ziehen) und umsortieren (Clip ziehen, gelbe Markierung zeigt die Stelle), Abspielkopf, Klick/Ziehen auf das Zeitlineal springt, Zoom (＋ − „Alles zeigen“ oder Strg + Mausrad), Mausrad scrollt bei Zoom.

## 0.4.0
- **Neu: Übergänge zwischen Clips** – 28 Stück (Überblenden, Über Schwarz/Weiß, Wischen, Schieben, Kreis, Pixel, Zoom, Wisch-Unschärfe …).
  - Registerkarte „Clip“: Art und Dauer des Übergangs zum nächsten Clip, „Auf alle Clips anwenden“
  - Der Ton wird weich überblendet; die Gesamtlänge verkürzt sich um die Überlappung
  - In der Timeline sind Übergänge mit „⇄“ markiert, die Clipblöcke überlappen
  - Zu lange Dauern werden automatisch begrenzt; Teilen eines Clips setzt zwischen den Hälften einen harten Schnitt
  - Eigene Übergänge: `transitions.json` in `%APPDATA%\ClipForge\presets` (Felder `id`, `name`, `xfade` = FFmpeg-Name)

## 0.3.0
- **Neu: Tonspuren** – A1 Ton, A2 Musik, A3 frei neben der Videospur V1.
  - „Ton vom Clip trennen“ (folgt dem Clip), „Wieder verbinden“, Audio/Musik importieren (auch per Drag & Drop)
  - Blöcke in der Timeline mit der Maus verschieben/kürzen, Einrasten an Clipgrenzen, Wellenform
  - Registerkarte „Ton“: Start, Von/Bis, Lautstärke, Ein-/Ausblenden, Geschwindigkeit, Loop, Stumm, Rückwärts
  - Mischpult je Spur, Ducking (Musik leiser bei Sprache), Lautheit −14 LUFS
- Projekte aus 0.1/0.2 lassen sich weiter öffnen.
- Schrift „ClipForge Metal“ hat jetzt Ziffern 0–9 und Satzzeichen (. , : ; ! ? - ' " + / ( ) %).

## 0.2.0
- **Neu: Registerkarte „Bild“** – Licht, Kontrast und Farben pro Clip anpassen:
  - Licht: Helligkeit, Kontrast, Mitteltöne, Lichter, Schatten
  - Farbe: Farbtemperatur (kalt ↔ warm), Tönung (grün ↔ magenta), Sättigung, Dynamik, Farbton
  - Detail: Schärfe, Rauschen reduzieren (hilft bei dunklen Aufnahmen)
  - „Automatisch Helligkeit und Kontrast ausgleichen“
  - 12 Voreinstellungen (z. B. „Dunkle Szene retten“, „Zu hell: Lichter retten“, „Warm“, „Matt / Film-Look“)
  - Vorher/Nachher-Standbild an der Abspielposition, „Zurücksetzen“, „Auf alle Clips anwenden“
  - Clips mit Korrektur sind in der Timeline mit „◐ Bild“ markiert
  - Eigene Voreinstellungen: `grades.json` in `%APPDATA%\ClipForge\presets` (gleicher Aufbau wie `presets/grades.json`)
- Projekte aus 0.1.x lassen sich weiter öffnen.

## 0.1.0
- Erste Version: Schnitt, Format-Presets (YouTube, Shorts, TikTok, Reels, Instagram), Effekte inkl. Glitch,
  Text mit eigener Schrift, Export, Update-Check, Installer.
