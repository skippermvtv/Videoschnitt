@echo off
REM Baut FATE-VIDEOSCHNITT-Setup.exe lokal unter Windows (Alternative zu GitHub).
REM Voraussetzungen: Python 3.12+ (python.org, Haken bei "Add to PATH") und Inno Setup 6 (jrsoftware.org).
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (echo Python wurde nicht gefunden. Bitte von python.org installieren. & pause & exit /b 1)

if not exist .venv ( python -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || (echo Installation fehlgeschlagen & pause & exit /b 1)

if not exist vendor\ffmpeg\ffmpeg.exe (
  echo Lade FFmpeg herunter ...
  mkdir vendor\ffmpeg 2>nul
  powershell -NoProfile -Command "Invoke-WebRequest 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile ffmpeg.zip; Expand-Archive ffmpeg.zip -DestinationPath ffmpeg_tmp -Force; $e = Get-ChildItem ffmpeg_tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1; Copy-Item $e.FullName vendor\ffmpeg\; Copy-Item (Join-Path $e.DirectoryName 'ffprobe.exe') vendor\ffmpeg\"
)

pyinstaller --noconfirm --clean --windowed --name FATE-VIDEOSCHNITT --icon assets\icon.ico --add-data "presets;presets" --add-data "assets;assets" --add-data "THIRD_PARTY.txt;." --add-data "fonts;fonts" --add-data "vendor/ffmpeg;vendor/ffmpeg" main.py || (echo PyInstaller fehlgeschlagen & pause & exit /b 1)

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% installer.iss
  echo.
  echo Fertig: installer_output\FATE-VIDEOSCHNITT-Setup.exe
) else (
  echo Inno Setup 6 nicht gefunden. Das Programm liegt trotzdem fertig in dist\FATE-VIDEOSCHNITT\FATE-VIDEOSCHNITT.exe
)
pause
