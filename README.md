# FATE VIDEOSCHNITT – Videoschnitt für Windows

Eigenes Videoschnittprogramm mit **Presets für YouTube, Shorts, TikTok, Reels und Instagram**, 31 Effekten (u. a. Glitch, VHS, Neon, Comic),
**Bildkorrektur** (mit Farbrädern, Kurven und LUT), **Greenscreen**, **Tonspuren** (Ton trennen, Musik, Ducking), **28 Übergängen**, **Untertiteln** (auch automatisch aus Sprache),
**Bild-in-Bild**, **Keyframe-Bewegung**, Text mit Animationen, eigener Schrift und eingebautem **Update-Check**.
Gerendert wird mit FFmpeg (wird in die Setup.exe eingebaut – Nutzer brauchen weder Python noch FFmpeg).

Eine Kurzanleitung findest du im Programm unter **Hilfe → Kurzanleitung (F1)**.

## Setup.exe über GitHub bauen lassen (ohne Python auf deinem PC)

1. Kostenloses Konto auf <https://github.com> anlegen und **New repository** wählen.
   Name z. B. `clipforge`, Sichtbarkeit **Public** (nötig, damit der Update-Check ohne Login funktioniert).
2. Den **Inhalt dieses Ordners** hochladen: im neuen Repository *uploading an existing file* anklicken
   und alle Dateien und Ordner per Drag & Drop hineinziehen (auch den Ordner `.github`), dann **Commit changes**.
   Prüfe danach, dass unter `.github/workflows/` die Datei `build.yml` vorhanden ist.
3. Rechts auf **Releases → Create a new release**. Bei *Choose a tag* `v0.1.0` eintippen
   und *Create new tag* wählen, dann **Publish release**.
4. Reiter **Actions**: Der Lauf „Setup.exe bauen“ dauert ca. 10–15 Minuten.
   Danach hängt `FATE-VIDEOSCHNITT-Setup.exe` am Release (Reiter *Releases*). Das ist die Datei zum Weitergeben.
5. Wird der Lauf rot: auf den Lauf klicken, die Fehlermeldung kopieren – damit lässt sich der Fehler gezielt beheben.

Beim Bauen trägt GitHub automatisch Versionsnummer und Repository-Namen in `app/version.py` ein.
Windows zeigt bei der ersten Installation evtl. „Unbekannter Herausgeber“ (SmartScreen): *Weitere Informationen → Trotzdem ausführen*.
Das verschwindet nur mit einem kostenpflichtigen Code-Signing-Zertifikat.

## Updates ausliefern

1. Geänderte Dateien ins Repository hochladen.
2. Neues Release mit höherer Nummer veröffentlichen (`v0.1.1`, `v0.2.0` …).
3. Installierte Programme melden beim Start „Update verfügbar“ und installieren es nach Bestätigung
   (außerdem: *Hilfe → Nach Updates suchen*).

**Presets ohne neues Release:** JSON-Dateien in `%APPDATA%\FATE VIDEOSCHNITT\presets` (Menü *Hilfe → Eigene Presets-Ordner öffnen*)
ergänzen oder überschreiben die mitgelieferten Presets.

## Schrift

Mitgeliefert ist `fonts/FateMetal.ttf` (Gothic/Metal, A–Z, a–z, Umlaute ÄÖÜäöü, Ziffern 0–9 und die gängigen Satzzeichen).
Weitere `.ttf`/`.otf`-Dateien in den Ordner `fonts/` legen und hochladen – sie werden in die Setup.exe eingebaut und erscheinen
unter *Text → Schrift*. Enthält ein Text Zeichen, die die Schrift nicht hat, warnt das Programm. Nur Schriften verwenden, die du weitergeben darfst.

## Aufbau

```
main.py                    Programmstart
app/core/effects.py        Effekt-Bibliothek (FFmpeg-Filter) – neue Effekte hier ergänzen
app/core/exporter.py       baut den FFmpeg-Aufruf (Clips, Format, Effekte, Text, Fades)
app/core/presets.py        lädt Presets (mitgeliefert + eigene)
app/core/grade.py          Bildkorrektur (Regler, Farbräder, Kurven, LUT → FFmpeg-Filter, Vorher/Nachher-Bild)
app/core/audiomix.py       Tonspuren mischen (Spuren, Loop, Fades, Ducking, Lautheit)
app/core/waveform.py       Wellenform-Bilder für die Timeline
app/core/updater.py        Update-Check über GitHub Releases
app/ui/                    Oberfläche (PySide6)
presets/*.json             Formate, Export-Qualitäten, Looks, Bild-Voreinstellungen
tests/                     Tests (laufen auch automatisch auf GitHub)
installer.iss, build.bat   Installer-Skript / lokaler Build
.github/workflows/         GitHub baut die Setup.exe
```

### Neuen Effekt hinzufügen (Beispiel)

```python
@effect("sepia2", "Mein Effekt", "Farbe", 50)
def _mein_effekt(i, o, k, c):          # k = Stärke 0.0 … 1.0
    return chain(i, o, f"eq=contrast={n(1 + k)}")
```

## Lokal bauen (Alternative)

Python 3.12+ und Inno Setup 6 installieren, dann `build.bat` doppelklicken.

## Oberfläche und Live-Vorschau (ab 1.4)

- **Oben links** die Reiter: *Medien* (Raster mit Vorschaubildern, Import, Suche), *Format*, *Bild*, *Effekte*, *Text*, *Clip*, *Ton*, *Bild-in-Bild*, *Untertitel*, *Bewegung*. Rechts daneben der Knopf **EXPORT**.
- **Oben rechts** die Vorschau mit Zeitcode, Suchleiste über das ganze Projekt und den Knöpfen Anfang / Abspielen / Ende.
- **Unten** die Timeline mit Werkzeugleiste und Zoomregler.
- **● Live**: Änderungen sind nach kurzer Zeit im Player zu sehen. Das Programm rechnet dafür im Hintergrund einen kurzen Abschnitt (Einstellung `live_len`, Standard 6 s) am Abspielkopf in kleiner Auflösung. Während es rechnet, steht neben dem Knopf ein Hinweis.
- **Masken** (Effekte der Kategorie *Maske*): Form, Mitte, Größe und weiche Kante beim gewählten Effekt-Block.

## Effekt-Spur (ab 1.2)

Alle Effekte liegen als Blöcke auf der Spur **FX Effekte** ganz oben in der Timeline – so siehst du auf einen Blick, wann welcher Effekt wirkt.
- **Anlegen:** Effekt im Reiter *Effekte* in die Spur ziehen, doppelklicken oder „＋ Auf Effekt-Spur“ (legt ihn am Abspielkopf ab).
- **Verschieben:** Block in der Mitte anfassen (rastet an Clipgrenzen und anderen Blöcken ein). **Länge ändern:** linken oder rechten Rand ziehen.
- **Einstellen:** Block anklicken – im Reiter *Effekte* änderst du Stärke, Anfang und Ende. **Löschen:** Entf.
- Überlappende Blöcke liegen untereinander (bis zu 3 Zeilen). Derselbe Effekt kann beliebig oft vorkommen. Ein Look (Reiter *Effekte*) ersetzt alle Blöcke.
- Alte Projekte laden unverändert: Effekte ohne Zeitfenster erscheinen als Block über die ganze Länge.

## Farbe und Greenscreen (ab 1.3)

Reiter **Bild** (pro Clip):
- **Farbräder** für Schatten, Mitten und Lichter: im Rad ziehen = Farbstich in diese Richtung, Doppelklick = zurücksetzen.
- **Kurven** für Helligkeit, Rot, Grün und Blau: Klick setzt einen Punkt, ziehen verschiebt, Rechtsklick (oder Doppelklick auf den Punkt) löscht. Bis zu 12 Punkte je Kurve.
- **LUT** (`.cube`, 3D und 1D; auch `.3dl`): „LUT laden …“ kopiert die Datei in den Datenordner (`%APPDATA%\FATE VIDEOSCHNITT\luts`), „Stärke“ mischt sie ab. Fehlt sie später, meldet das Programm sie bei „Fehlende Dateien suchen …“.
- Neue Voreinstellungen: Teal & Orange, S-Kurve, Verblasster Film, Cyber.

Reiter **Bild-in-Bild**: **Chroma-Key** macht eine Hintergrundfarbe (Grün, Blau oder frei gewählt) durchsichtig. *Toleranz* bestimmt, wie ähnliche Farben mit entfernt werden, *Weiche Kante* glättet den Rand, *Farbsaum entfernen* nimmt grüne/blaue Ränder weg. „Als Vollbild darüberlegen“ setzt Mitte und 100 % Breite; das Hauptvideo darunter ist der neue Hintergrund.

## Vorschau und Geschwindigkeit (ab 0.9)

- **▶ Vorschau ab Abspielkopf** (Strg+P) zeigt das fertige Ergebnis mit allen Effekten ab der Stelle des Abspielkopfs. Länge und Qualität stellst du im Reiter **Format** unter „Vorschau und Leistung“ ein. Die Vorschau wird gespeichert; ohne Änderung startet sie sofort.
- Im Reiter Format kannst du **„Grafikkarte beim Export nutzen“** einschalten. Findet das Programm keine passende Grafikkarte, läuft der Export wie gewohnt auf dem Prozessor.
- Der Player selbst spielt weiterhin die Quelldateien (ohne Effekte) – das ist bewusst schnell und genau zum Schneiden.

## Drehen, Zuschneiden und Bewegung (ab 0.8)

Clip anklicken → Registerkarte **Bewegung**. Oben drehst, spiegelst und schneidest du zu. Darunter wählst du eine Voreinstellung (z. B. „Ken Burns“) oder legst Keyframes an:
Zoom 100 % ist die Originalgröße, ab 101 % wird hineingezoomt; der Schwenk wirkt nur bei Zoom. Die Bewegung siehst du in „Vorschau mit Effekten“ und im Export.

## Untertitel und Textanimationen (ab 0.7)

- Registerkarte **Untertitel**: „+ Eintrag“ legt einen Untertitel am Abspielkopf an; **SRT importieren/speichern** tauscht Dateien mit anderen Programmen. Aussehen und Animation gelten für alle Untertitel.
- Im Reiter **Text** gibt es 8 Animationen (u. a. Schreibmaschine, Hüpfen, Wackeln) und einen dunklen Kasten.
- Die Vorschau im Player zeigt Texte nicht – prüfe sie mit „Vorschau mit Effekten“.

### Automatische Untertitel einrichten (einmalig)

**Einfach (ab 1.1):** Im Reiter Untertitel auf „Untertitel automatisch erzeugen“ klicken (oder Hilfe → Spracherkennung einrichten). FATE VIDEOSCHNITT fragt nach dem Modell und lädt whisper.cpp und das Modell selbst herunter (base: ca. 148 MB). Danach läuft die Erkennung komplett auf deinem PC; das Ergebnis bitte kurz prüfen.

**Von Hand (falls der Download nicht klappt):**
1. Von <https://github.com/ggml-org/whisper.cpp/releases> die Windows-Datei (x64) herunterladen und entpacken.
2. Ein Modell von <https://huggingface.co/ggml-org/whisper.cpp/tree/main> laden, z. B. `ggml-base.bin` (klein, schnell) oder `ggml-small.bin` (genauer).
3. `whisper-cli.exe` samt DLLs und das Modell in den Ordner `%APPDATA%\FATE VIDEOSCHNITT\whisper` legen.

## Umbenennung (ab 1.2)

Das Programm heißt jetzt **FATE VIDEOSCHNITT** (vorher ClipForge). Beim Update bleiben Einstellungen, eigene Presets, Schriften, Spracherkennung und der Autosave erhalten: der Ordner `%APPDATA%\ClipForge` wird beim ersten Start in `%APPDATA%\FATE VIDEOSCHNITT` umbenannt. Projektdateien (`.cforge`) und die Schrift (jetzt „FATE Metal“) laden wie bisher. Die Setup-Datei heißt `FATE-VIDEOSCHNITT-Setup.exe`; sie ersetzt die alte Installation (die alte `ClipForge.exe` wird entfernt).

## Wenn etwas nicht klappt (ab 1.1)

- **Hilfe → Diagnose und Fehlerbericht** testet FFmpeg und die Grafikkarten-Encoder und zeigt das Protokoll. „Bericht kopieren“ und in die Nachricht einfügen – der Bericht enthält keine Projektinhalte.
- Bei einem unerwarteten Fehler erscheint ein Dialog mit demselben Knopf. Die Dateien liegen in `%APPDATA%\FATE VIDEOSCHNITT\logs` (`videoschnitt.log`, bei harten Abstürzen `crash.txt`).

## Setup.exe signieren (optional, ab 1.1)

Ohne Signatur zeigt Windows SmartScreen bei neuen Programmen eine Warnung. Mit einem Code-Signing-Zertifikat (.pfx, kostenpflichtig) wird die Setup.exe beim Bauen automatisch signiert:
1. Zertifikat in Base64 umwandeln (PowerShell): `[Convert]::ToBase64String([IO.File]::ReadAllBytes("zertifikat.pfx")) | Set-Clipboard`
2. Im Repository unter Settings → Secrets and variables → Actions zwei Secrets anlegen: `SIGN_PFX_BASE64` (der kopierte Text) und `SIGN_PFX_PASSWORD`.
3. Nächstes Release bauen – der Schritt „Setup.exe signieren“ läuft automatisch. Ohne diese Secrets wird er übersprungen.

## Standbilder und Bild-in-Bild (ab 0.6)

- Bilder importieren wie Videos; sie liegen 5 s auf der Timeline (Länge unter „Clip“ änderbar).
- **▣ Bild-in-Bild hinzufügen …** legt ein Video oder Bild auf die Spur **V2** an der Stelle des Abspielkopfs. Position, Größe, Deckkraft und Blenden stellst du in der Registerkarte „Bild-in-Bild“ ein.

## Bedienung der Timeline (ab 0.5)

- Klick auf einen Clip wählt ihn aus. **Rand ziehen** kürzt, **in der Mitte ziehen** ändert die Reihenfolge.
- Klick oder Ziehen auf das Zeitlineal setzt den Abspielkopf. **Strg + Mausrad** zoomt, Mausrad scrollt bei Zoom.
- **Strg+Z / Strg+Y** machen Änderungen rückgängig bzw. stellen sie wieder her. Alle 30 Sekunden wird automatisch gesichert.

## Übergänge (ab 0.4)

Clip anklicken → Registerkarte **Clip** → „Übergang zum nächsten Clip“: Art und Dauer wählen. Der Übergang überlappt die beiden Clips, der Ton wird mitüberblendet.

## Töne und Musik (ab 0.3)

- Spuren: **V1** Video, **A1 Ton**, **A2 Musik**, **A3 frei**.
- **Ton vom Clip trennen**: Clip anklicken → „♪ Ton vom Clip trennen“. Der Ton liegt dann als eigener Block auf A1 und folgt dem Clip beim Verschieben.
- **Musik / Audio hinzufügen**: Knopf unter der Timeline oder Datei ins Fenster ziehen (reine Audiodateien landen auf A2).
- Blöcke mit der Maus verschieben (auch auf andere Spuren), an den Rändern kürzen; sie rasten an Clipgrenzen ein.
- Registerkarte **Ton**: Start, Von/Bis, Lautstärke, Ein-/Ausblenden, Geschwindigkeit, Wiederholen (Loop), Stumm, Rückwärts;
  Mischpult je Spur, **Ducking** (Musik wird leiser, wenn Ton spricht) und **Lautheit angleichen** (−14 LUFS).
- Die Vorschau im Player spielt nur die Quelldatei; das Ergebnis mit Musik hörst du in „Vorschau mit Effekten“ oder im Export.

## Bekannte Grenzen

- Nur eine Bild-in-Bild-Spur (V2); Overlay-Ton wird nicht gemischt.
- Chroma-Key gibt es nur für Bild-in-Bild (V2), nicht für die Hauptspur. Die Schlüsselfarbe wählst du aus Grün, Blau oder dem Farbdialog (keine Pipette im Bild).
- Die Vorschau mit Effekten wird vorab berechnet (kein Echtzeit-Playback mit Effekten).
