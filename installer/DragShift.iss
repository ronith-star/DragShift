; Inno Setup script — per-user install, no admin rights needed.
#define AppVersion GetEnv("DS_VERSION")
#if AppVersion == ""
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6C1E2B0A-7D5F-4E8B-9F3A-D7A5F1C2B3E4}
AppName=Orbit
AppVersion={#AppVersion}
AppPublisher=Orbit
DefaultDirName={localappdata}\Programs\Orbit
DefaultGroupName=Orbit
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Orbit-Setup
SetupIconFile=..\dragshift\assets\dragshift.ico
UninstallDisplayIcon={app}\Orbit.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "autostart"; Description: "Start Orbit when I sign in to Windows"; Flags: checkedonce
Name: "contextmenu"; Description: "Add ""Orbit"" to the right-click menu for files"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Orbit\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Orbit"; Filename: "{app}\Orbit.exe"
Name: "{autodesktop}\Orbit"; Filename: "{app}\Orbit.exe"; Tasks: desktopicon
Name: "{usersendto}\Orbit"; Filename: "{app}\Orbit.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Orbit"; ValueData: """{app}\Orbit.exe"" --quiet"; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\*\shell\Orbit"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Orbit…"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\Orbit"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\Orbit.exe"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Orbit"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Orbit\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Orbit.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Orbit"; Flags: uninsdeletekey

[Run]
Filename: "{app}\Orbit.exe"; Description: "Launch Orbit now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM Orbit.exe"; Flags: runhidden; RunOnceId: "KillOrbit"
