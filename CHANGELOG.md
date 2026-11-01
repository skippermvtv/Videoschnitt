# Änderungen

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
