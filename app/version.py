"""Name, Version und GitHub-Repository für den Update-Check.

Beim Release wird VERSION automatisch aus dem Git-Tag (z. B. v1.4.7) gesetzt,
siehe .github/workflows/build.yml.
"""

APP_NAME = "FATE VIDEOSCHNITT"
APP_SLUG = "FATE-VIDEOSCHNITT"            # für Dateinamen ohne Leerzeichen (Setup, Programmdatei)
DATA_DIR_NAME = "FATE VIDEOSCHNITT"       # Ordner unter %APPDATA% (Einstellungen, Presets, Protokolle, Spracherkennung)
LEGACY_DATA_DIR_NAME = "ClipForge"        # früherer Name; dieser Ordner wird beim ersten Start umbenannt
VERSION = "1.4.7"

# >>> HIER anpassen: dein GitHub-Benutzername und der Name deines Repositories <<<
GITHUB_REPO = "DEIN-BENUTZERNAME/clipforge"
