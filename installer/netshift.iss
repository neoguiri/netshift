; Installeur Windows de NetShift (Inno Setup 6)
; Compilation :  iscc /DAppVersion=1.1.0 installer\netshift.iss
; Prérequis : dist\NetShift.exe (construit par PyInstaller, voir build_exe.bat)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{F84E7B65-27E7-4166-B6C0-79E599D4EAB9}
AppName=NetShift
AppVersion={#AppVersion}
AppVerName=NetShift {#AppVersion}
AppPublisher=neoguiri
AppPublisherURL=https://github.com/neoguiri/netshift
AppSupportURL=https://github.com/neoguiri/netshift/issues
AppUpdatesURL=https://github.com/neoguiri/netshift/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\NetShift
DefaultGroupName=NetShift
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=NetShift-Setup-{#AppVersion}
SetupIconFile=..\assets\netshift.ico
UninstallDisplayIcon={app}\NetShift.exe
UninstallDisplayName=NetShift
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\NetShift.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\NetShift"; Filename: "{app}\NetShift.exe"
Name: "{autodesktop}\NetShift"; Filename: "{app}\NetShift.exe"; Tasks: desktopicon

[Run]
; shellexec : respecte le manifeste de l'exe (demande des droits administrateur)
Filename: "{app}\NetShift.exe"; Description: "{cm:LaunchProgram,NetShift}"; Flags: nowait postinstall skipifsilent shellexec

; Les presets, l'historique et les réglages (%APPDATA%\NetShift) sont conservés à la désinstallation.
