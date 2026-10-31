; Inno Setup script: per-user installer for Word Session (no admin rights, no Python).
; Build with: iscc /DAppVersion=1.0.0 packaging\installer.iss
; (packaging\build.ps1 -Installer does this after building dist\WordSession.)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Word Session"
#define AppExe "word-session-app.exe"
#define CliExe "word-session.exe"

[Setup]
; A fixed GUID identifies this application across versions (keep it unchanged).
AppId={{6F0B7C52-3D4E-4B8A-9C1D-5A2E7F9B1C34}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Word Session
DefaultDirName={localappdata}\Programs\WordSession
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist
OutputBaseFilename=WordSession-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Close a running copy through our own quit-app command instead of Restart Manager.
CloseApplications=no
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Start Word Session when I sign in"; Flags: unchecked

[Files]
Source: "..\dist\WordSession\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Word Session"; Filename: "{app}\{#AppExe}"; Comment: "Save and restore Word sessions"

[Registry]
; Same value as autostart.enable: HKCU\...\Run, name WordSession, quoted path of the app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WordSession"; ValueData: """{app}\{#AppExe}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start Word Session now"; Flags: nowait postinstall skipifsilent

[Code]
{ Stop a running instance through "word-session.exe quit-app" (exit code 0 also when
  nothing runs). The command reads the instance file, so it honours WORD_SESSION_HOME. }
procedure StopRunningInstance(AppDir: String);
var
  Cli: String;
  ResultCode: Integer;
begin
  Cli := AppDir + '\{#CliExe}';
  if FileExists(Cli) then
    Exec(Cli, 'quit-app', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ Before installing over an older copy, stop the application so its files can be replaced. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningInstance(ExpandConstant('{app}'));
  Result := '';
end;

{ Before uninstalling, stop the application so its files can be removed. }
function InitializeUninstall(): Boolean;
begin
  StopRunningInstance(ExpandConstant('{app}'));
  Result := True;
end;

{ After uninstalling, say that the user's data was left alone. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usDone) and not UninstallSilent then
    MsgBox('Word Session was removed.' + #13#10 + #13#10 +
      'Your saved sessions and settings were not deleted. They remain in' + #13#10 +
      ExpandConstant('{userappdata}\word-session') + #13#10 +
      'and ' + ExpandConstant('{localappdata}\word-session') + '.',
      mbInformation, MB_OK);
end;
