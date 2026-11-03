#ifndef AppVersion
  #define AppVersion "3.5"
#endif
[Setup]
AppId={{0CCB50C8-66A7-4CFB-AB7A-38B8B5F325A4}
AppName=ShiftWheel
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\ShiftWheel
DefaultGroupName=ShiftWheel
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=release
OutputBaseFilename=ShiftWheelSetup-{#AppVersion}
SetupIconFile=assets\shiftwheel.ico
UninstallDisplayIcon={app}\ShiftWheel.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\ShiftWheel.Desktop
CloseApplications=no
DisableProgramGroupPage=yes
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start ShiftWheel when I sign in"; Flags: unchecked
[Files]
Source: "dist\ShiftWheel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\ShiftWheel"; Filename: "{app}\ShiftWheel.exe"
Name: "{autodesktop}\ShiftWheel"; Filename: "{app}\ShiftWheel.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ShiftWheel"; ValueData: """{app}\ShiftWheel.exe""""; Tasks: startup; Flags: uninsdeletevalue
[Run]
Filename: "{app}\ShiftWheel.exe"; Description: "Launch ShiftWheel"; Flags: nowait postinstall skipifsilent
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  if CurUninstallStep = usUninstall then
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'ShiftWheel', Command) then
      if CompareText(Command, '"' + ExpandConstant('{app}\ShiftWheel.exe') + '"') = 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'ShiftWheel');
end;
