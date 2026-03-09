; ─────────────────────────────────────────────────────────────────────────────
; steam_grunge_editor.iss — Inno Setup installer script
;
; Produces: SteamGrungeEditor-1.0.0-Setup.exe
;
; How to build:
;   1. Install Inno Setup 6 from https://jrsoftware.org/isdl.php
;   2. Run PyInstaller first to generate the dist/ folder
;   3. Open this .iss file in Inno Setup Compiler and click Build → Compile
;      OR from command line:
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" steam_grunge_editor.iss
; ─────────────────────────────────────────────────────────────────────────────

#define AppName      "Steam Grunge Editor"
#define AppVersion   "1.0.0"
#define AppPublisher "Huzzama"
#define AppURL       "https://github.com/Huzzama/Steam-Grunge"
#define AppExeName   "SteamGrungeEditor.exe"
#define AppID        "{{A3F2B8C1-4D5E-4F6A-B7C8-D9E0F1A2B3C4}"

; Path to PyInstaller output — adjust if needed
#define DistDir      "..\..\dist\SteamGrungeEditor"
#define IconFile     "..\..\app\assets\icon.ico"

[Setup]
; Unique ID — DO NOT change after first release (used for upgrades)
AppId={#AppID}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; Install to Program Files by default
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Output
OutputDir=..\..\dist\installer
OutputBaseFilename=SteamGrungeEditor-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes

; Appearance
WizardStyle=modern
WizardResizable=yes
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}

; Privileges — allow install without admin if possible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Minimum Windows version: Windows 10
MinVersion=10.0

; Allow upgrading previous installs cleanly
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Desktop shortcut (checked by default)
Name: "desktopicon";    Description: "{cm:CreateDesktopIcon}";    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Start menu shortcut
Name: "startmenuicon";  Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; All PyInstaller output files
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start menu
Name: "{group}\{#AppName}";            Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}";  Filename: "{uninstallexe}"

; Desktop (only if task selected)
Name: "{autodesktop}\{#AppName}";      Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the app after install
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up user data folder on uninstall (optional — comment out to keep user data)
; Type: filesandordirs; Name: "{localappdata}\GrungeStudio"

[Code]
// Optional: show a warning if a previous version is already installed
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    // Nothing extra needed — Inno handles upgrades via AppId
  end;
end;
