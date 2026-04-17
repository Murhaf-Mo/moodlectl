[Setup]
AppName=moodlectl
AppVersion={#AppVersion}
AppPublisher=Murhaf-Mo
AppPublisherURL=https://github.com/Murhaf-Mo/moodlectl
AppSupportURL=https://github.com/Murhaf-Mo/moodlectl/issues
AppUpdatesURL=https://github.com/Murhaf-Mo/moodlectl/releases
DefaultDirName={autopf}\moodlectl
DefaultGroupName=moodlectl
OutputDir=Output
OutputBaseFilename=moodlectl-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
PrivilegesRequired=admin
DisableProgramGroupPage=yes
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\moodlectl.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\moodlectl\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Registry]
; Add install directory to system PATH
Root: HKLM; \
  Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
  ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; \
  Check: not IsPathInPath('{app}')

[Code]
function IsPathInPath(NewPath: string): Boolean;
var
  CurrentPath: string;
begin
  if RegQueryStringValue(HKLM,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', CurrentPath) then
    Result := Pos(LowerCase(NewPath), LowerCase(CurrentPath)) > 0
  else
    Result := False;
end;

[UninstallRegistry]
; Remove from PATH on uninstall
Root: HKLM; \
  Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
  ValueType: expandsz; ValueName: "Path"; \
  ValueData: ""

[Icons]
Name: "{group}\Uninstall moodlectl"; Filename: "{uninstallexe}"

[Run]
Filename: "cmd.exe"; \
  Parameters: "/c moodlectl --help"; \
  Flags: nowait postinstall skipifsilent; \
  Description: "Verify installation (run moodlectl --help)"
