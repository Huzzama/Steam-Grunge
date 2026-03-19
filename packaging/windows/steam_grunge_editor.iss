; ─────────────────────────────────────────────────────────────────────────────
; steam_grunge_editor.iss — Inno Setup 6 installer script
;
; Produces: SteamGrungeEditor-{version}-Setup.exe
;
; How to build:
;   1. Install Inno Setup 6 — https://jrsoftware.org/isdl.php
;   2. Run PyInstaller first:
;        pyinstaller packaging\windows\steam_grunge_editor.spec --noconfirm --clean
;   3. Build installer:
;        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=2.1.0 steam_grunge_editor.iss
;      Or open in Inno Setup Compiler IDE and press F9.
;
; v2.1.0 changes:
;   - AppVersion bumped to 2.1.0
;   - UninstallDelete section enabled — cleans up logs folder on uninstall
;     (new in v2.1.0: steamSync writes rotating logs to %LOCALAPPDATA%)
;   - Added {cm:AdditionalIcons} task defaults adjusted (desktop unchecked,
;     start menu checked — matches typical app installer UX)
;   - MinVersion confirmed Windows 10 (unchanged)
; ─────────────────────────────────────────────────────────────────────────────

#define AppName      "Steam Grunge Editor"
#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#define AppPublisher "Huzzama"
#define AppURL       "https://github.com/Huzzama/Steam-Grunge"
#define AppExeName   "SteamGrungeEditor.exe"

; DO NOT change AppID after first release — Inno uses it to detect upgrades
; and cleanly replace previous installs without leaving orphan entries.
#define AppID        "{{A3F2B8C1-4D5E-4F6A-B7C8-D9E0F1A2B3C4}"

; Paths relative to this .iss file (packaging\windows\)
#define DistDir      "..\..\dist\SteamGrungeEditor"
#define IconFile     "..\..\app\assets\icon.ico"

; ─────────────────────────────────────────────────────────────────────────────
[Setup]
; ── Identity ──────────────────────────────────────────────────────────────────
AppId={#AppID}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; ── Install location ──────────────────────────────────────────────────────────
; {autopf} = Program Files (x86) on 32-bit, Program Files on 64-bit
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; ── Output ────────────────────────────────────────────────────────────────────
OutputDir=..\..\dist\installer
OutputBaseFilename=SteamGrungeEditor-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
; Include version info in the installer exe itself
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

; ── Appearance ────────────────────────────────────────────────────────────────
WizardStyle=modern
WizardResizable=yes
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

; ── Privileges ────────────────────────────────────────────────────────────────
; Install to per-user Program Files if possible; fall back to system-wide.
; This avoids UAC prompts for most users while still supporting admin installs.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; ── Platform ──────────────────────────────────────────────────────────────────
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ── Upgrade behaviour ─────────────────────────────────────────────────────────
; Close running instances before upgrading — prevents locked-file errors
CloseApplications=yes
RestartApplications=no

; ─────────────────────────────────────────────────────────────────────────────
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ─────────────────────────────────────────────────────────────────────────────
[Tasks]
; Desktop shortcut — unchecked by default (less aggressive than most installers)
Name: "desktopicon";   Description: "{cm:CreateDesktopIcon}";      GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Start menu shortcut — checked by default
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

; ─────────────────────────────────────────────────────────────────────────────
[Files]
; All PyInstaller output — recurse into subfolders for Qt plugins, PySide6 DLLs
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ─────────────────────────────────────────────────────────────────────────────
[Icons]
; Start menu
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; Desktop (only created if user selected the task above)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

; ─────────────────────────────────────────────────────────────────────────────
[Run]
; Offer to launch immediately after install — skipped in silent (/SILENT) mode
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

; ─────────────────────────────────────────────────────────────────────────────
[UninstallDelete]
; Remove the rotating log files written by steamSync (v2.1.0+).
; These live in %LOCALAPPDATA%\steam-grunge-editor\logs\ on Windows.
; Comment these lines out if you want logs preserved after uninstall.
Type: filesandordirs; Name: "{localappdata}\steam-grunge-editor\logs"

; Remove the settings file (API keys, preferences) — comment out to keep.
; Type: files; Name: "{localappdata}\steam-grunge-editor\data\settings.json"

; ─────────────────────────────────────────────────────────────────────────────
[Code]
// Inno Setup Pascal script
// Runs at the start of the install step — nothing extra needed since
// Inno handles upgrades via AppId. Placeholder kept for future hooks.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    // Reserved for future pre-install actions (e.g. migrating user data)
  end;
end;
