; Inno-Setup-Skript: erzeugt installer_output\FATE-VIDEOSCHNITT-Setup.exe
; Aufruf (macht der GitHub-Workflow / build.bat automatisch):
;   ISCC.exe /DMyAppVersion=0.1.0 installer.iss

#define MyAppName "FATE VIDEOSCHNITT"
#define MyAppExe "FATE-VIDEOSCHNITT.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{B6F3C2E4-5A7D-4F1E-9C0A-3D2E8B7A1F55}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=FATE-VIDEOSCHNITT-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\icon.ico
ArchitecturesInstallIn64BitMode=x64compatible
; Ohne Administratorrechte installierbar (nur für den aktuellen Benutzer), auf Wunsch für alle
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExe}
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop erstellen"; GroupDescription: "Zusätzliche Symbole:"

[InstallDelete]
; Update von „ClipForge“: alte Programmdatei und alte Verknüpfungen entfernen
Type: files; Name: "{app}\ClipForge.exe"
Type: files; Name: "{autoprograms}\ClipForge.lnk"
Type: files; Name: "{autodesktop}\ClipForge.lnk"

[Files]
Source: "dist\FATE-VIDEOSCHNITT\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD_PARTY.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{#MyAppName} jetzt starten"; Flags: nowait postinstall skipifsilent
