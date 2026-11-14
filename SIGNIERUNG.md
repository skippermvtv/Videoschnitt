# Signierung (Setup und Programm digital unterschreiben)

**Warum?** Windows 11 mit *Smart App Control* blockiert unsignierte Programme (Fehler 4551 beim Update). Das Programm ist nicht
fehlerhaft, es fehlt nur die digitale Unterschrift. Eine Ausnahme für einzelne Programme gibt es bei Smart App Control nicht.

**Stand:** Der Build ist vorbereitet. Sobald ein Zertifikat als Secret hinterlegt ist, signiert er automatisch
(1) alle noch unsignierten `.exe`, `.dll` und `.pyd` im Programmordner, auch FFmpeg, und (2) danach die `Setup.exe`.
Ohne Zertifikat passiert nichts, der Build läuft wie bisher. Die Skripte sind unter Windows noch nicht mit echtem Zertifikat gelaufen.

## Was fehlt: ein Zertifikat
| Weg | Kosten (ungefähr) | Für wen | Bemerkung |
|---|---|---|---|
| Azure Artifact Signing (früher Trusted Signing) | rund 10 $/Monat | Firmen in USA, Kanada, EU, UK; Einzelpersonen nur USA/Kanada | Bequem für GitHub, aber in Deutschland nur mit eingetragenem Unternehmen |
| Code-Signing-Zertifikat von einer Zertifizierungsstelle (OV/IV) | rund 150–300 €/Jahr | weltweit | Neue Zertifikate liegen meist auf einem Token oder in der Cloud der Stelle, nicht mehr als `.pfx`-Datei. Für GitHub braucht man dann den Cloud-Signierdienst der Stelle |
| SignPath Foundation | kostenlos | nur Open-Source-Projekte | Verlangt eine OSI-Lizenz und nur eigenen Open-Source-Code. Das Projekt hat keine Lizenzdatei und enthält die Schrift „FATE Metal“ mit eingeschränkten Rechten, passt deshalb derzeit nicht |
| Microsoft Store (MSIX) | einmalige Kontogebühr | weltweit | Microsoft signiert selbst; würde aber einen anderen Installer bedeuten |

Hinweis: Eine Signatur macht aus einem Programm nicht sofort ein „bekanntes“. Für Smart App Control reicht eine gültige Signatur
einer vertrauenswürdigen Stelle, wenn die Cloud-Prüfung das Programm nicht schon vorher als sicher einstuft. SmartScreen kann bei
neuen Signaturen trotzdem noch eine Weile warnen.

## Einrichten, wenn du ein Zertifikat als `.pfx`-Datei hast
1. Datei in Base64 umwandeln (PowerShell): `[Convert]::ToBase64String([IO.File]::ReadAllBytes("zertifikat.pfx")) | Set-Clipboard`
2. GitHub → Repository → Settings → Secrets and variables → Actions → *New repository secret*:
   - `SIGN_PFX_BASE64` = Inhalt der Zwischenablage
   - `SIGN_PFX_PASSWORD` = Passwort der `.pfx`
3. Neuen Tag pushen. Im Build-Protokoll steht bei „Programmdateien signieren“, wie viele Dateien signiert wurden.

## Wenn das Zertifikat in der Cloud liegt (Azure, SSL.com, DigiCert …)
Dann braucht der Build statt `tools/sign-files.ps1` den Signierdienst des Anbieters. Sag mir, welchen Anbieter du nimmst, dann baue ich
den passenden Schritt ein und prüfe die Einstellungen.

## Bekannte Lücke
Der Deinstaller (`unins000.exe`), den Inno Setup erzeugt, wird noch nicht signiert. Das geht mit dem Inno-Befehl `SignTool` und
lässt sich nachziehen, sobald ein Zertifikat vorhanden ist.
