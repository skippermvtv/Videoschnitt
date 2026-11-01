; Inno-Setup-Skript: erzeugt installer_output\ClipForge-Setup.exe
; Aufruf (macht der GitHub-Workflow / build.bat automatisch):
;   ISCC.exe /DMyAppVersion=0.1.0 installer.iss

#define MyAppName "ClipForge"
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
OutputBaseFilename=ClipForge-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Ohne Administratorrechte installierbar (nur für den aktuellen Benutzer), auf Wunsch für alle
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\ClipForge.exe
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop erstellen"; GroupDescription: "Zusätzliche Symbole:"

[Files]
Source: "dist\ClipForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD_PARTY.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\ClipForge.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\ClipForge.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ClipForge.exe"; Description: "ClipForge jetzt starten"; Flags: nowait postinstall skipifsilent
