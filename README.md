# ClipForge – Videoschnitt für Windows

Eigenes Videoschnittprogramm mit **Presets für YouTube, Shorts, TikTok, Reels und Instagram**,
**Glitch- und Retro-Effekten**, Text mit eigener Schrift und eingebautem **Update-Check**.
Gerendert wird mit FFmpeg (wird in die Setup.exe eingebaut – Nutzer brauchen weder Python noch FFmpeg).

## Setup.exe über GitHub bauen lassen (ohne Python auf deinem PC)

1. Kostenloses Konto auf <https://github.com> anlegen und **New repository** wählen.
   Name z. B. `clipforge`, Sichtbarkeit **Public** (nötig, damit der Update-Check ohne Login funktioniert).
2. Den **Inhalt dieses Ordners** hochladen: im neuen Repository *uploading an existing file* anklicken
   und alle Dateien und Ordner per Drag & Drop hineinziehen (auch den Ordner `.github`), dann **Commit changes**.
   Prüfe danach, dass unter `.github/workflows/` die Datei `build.yml` vorhanden ist.
3. Rechts auf **Releases → Create a new release**. Bei *Choose a tag* `v0.1.0` eintippen
   und *Create new tag* wählen, dann **Publish release**.
4. Reiter **Actions**: Der Lauf „Setup.exe bauen“ dauert ca. 10–15 Minuten.
   Danach hängt `ClipForge-Setup.exe` am Release (Reiter *Releases*). Das ist die Datei zum Weitergeben.
5. Wird der Lauf rot: auf den Lauf klicken, die Fehlermeldung kopieren – damit lässt sich der Fehler gezielt beheben.

Beim Bauen trägt GitHub automatisch Versionsnummer und Repository-Namen in `app/version.py` ein.
Windows zeigt bei der ersten Installation evtl. „Unbekannter Herausgeber“ (SmartScreen): *Weitere Informationen → Trotzdem ausführen*.
Das verschwindet nur mit einem kostenpflichtigen Code-Signing-Zertifikat.

## Updates ausliefern

1. Geänderte Dateien ins Repository hochladen.
2. Neues Release mit höherer Nummer veröffentlichen (`v0.1.1`, `v0.2.0` …).
3. Installierte Programme melden beim Start „Update verfügbar“ und installieren es nach Bestätigung
   (außerdem: *Hilfe → Nach Updates suchen*).

**Presets ohne neues Release:** JSON-Dateien in `%APPDATA%\ClipForge\presets` (Menü *Hilfe → Eigene Presets-Ordner öffnen*)
ergänzen oder überschreiben die mitgelieferten Presets.

## Eigene Schrift einbauen

`.ttf`/`.otf`-Datei in den Ordner `fonts/` legen und hochladen – sie wird in die Setup.exe eingebaut,
erscheint unter *Text → Schrift* und ist für neue Texte vorausgewählt. Nur Schriften verwenden, die du weitergeben darfst.

## Aufbau

```
main.py                    Programmstart
app/core/effects.py        Effekt-Bibliothek (FFmpeg-Filter) – neue Effekte hier ergänzen
app/core/exporter.py       baut den FFmpeg-Aufruf (Clips, Format, Effekte, Text, Fades)
app/core/presets.py        lädt Presets (mitgeliefert + eigene)
app/core/updater.py        Update-Check über GitHub Releases
app/ui/                    Oberfläche (PySide6)
presets/*.json             Formate, Export-Qualitäten, Looks
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

## Bekannte Grenzen von Version 0.1

- Eine Videospur plus Text (keine Übergänge zwischen Clips, kein separates Musikspur-Feld).
- Die Vorschau mit Effekten ist ein 8-Sekunden-Entwurf in halber Auflösung, kein Echtzeit-Playback.
- Nur Videodateien als Quelle (keine Standbilder).
