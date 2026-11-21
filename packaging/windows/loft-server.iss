; The Loft server's setup for Windows (Inno Setup 6). packaging/build_server.py compiles it with:
;   ISCC /DAppVersion=x.y.z /DSourceDir=<built loft-server folder> /DOutputDir=<dist>
;        /DOutputName=<file name, no .exe> /DIconFile=<loft.ico> loft-server.iss
;
; It installs for the person running it (no administrator needed) into
; %LOCALAPPDATA%\Programs\Loft Server, a folder Loft may write to, so it can update itself: the
; server downloads the next setup and runs it silently (src/loft/updates.py). What people start is
; "Loft Server.exe", the tray icon (packaging/windows/tray.py), which runs the server hidden and
; turns on starting with Windows the first time. Loft's own data stays in %LOCALAPPDATA%\Loft and
; is never touched, by installing or by uninstalling.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=<the built loft-server folder>
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef OutputName
  #define OutputName "loft-server-setup"
#endif

[Setup]
AppId={{C669BF7C-61C3-4541-875A-65E6DE146BB0}
AppName=Loft Server
AppVersion={#AppVersion}
AppVerName=Loft Server {#AppVersion}
AppPublisher=Spinjitsudoom
AppPublisherURL=https://github.com/Spinjitsudoom/Loft
AppSupportURL=https://github.com/Spinjitsudoom/Loft/issues
AppUpdatesURL=https://github.com/Spinjitsudoom/Loft/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Loft Server
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
#ifdef IconFile
SetupIconFile={#IconFile}
#endif
UninstallDisplayIcon={app}\Loft Server.exe
UninstallDisplayName=Loft Server
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; A running Loft is stopped (PrepareToInstall, below) so its files can be replaced; the last page
; starts it again.
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put an ""Open Loft"" shortcut on the desktop"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Files a newer version no longer has.
Type: filesandordirs; Name: "{app}\_internal"
; The first 0.1.3 setup started the server in a console from the Startup folder; the tray does it now.
Type: files; Name: "{userstartup}\Loft Server.lnk"

[Icons]
Name: "{autoprograms}\Loft Server"; Filename: "{app}\Loft Server.exe"; Comment: "Run Loft, with its icon in the notification area"
Name: "{autoprograms}\Open Loft"; Filename: "http://localhost:4545"; IconFilename: "{app}\Loft Server.exe"; Comment: "Open Loft in your browser"
Name: "{autodesktop}\Open Loft"; Filename: "http://localhost:4545"; IconFilename: "{app}\Loft Server.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Loft Server.exe"; Description: "Start Loft Server"; Flags: nowait postinstall skipifsilent
Filename: "{app}\README.txt"; Description: "Show how to use it"; Flags: shellexec nowait postinstall skipifsilent unchecked
; An update (run silently by Loft itself): start it again in the background.
Filename: "{app}\Loft Server.exe"; Parameters: "--background"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ""Loft Server.exe"" /IM loft-server.exe"; Flags: runhidden; RunOnceId: "StopLoft"

[Registry]
; Start with Windows (the tray's menu turns it on and off): removed with Loft.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Loft Server"; Flags: uninsdeletevalue dontcreatekey

[Code]
// Loft must be closed before its files are replaced.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "Loft Server.exe" /IM loft-server.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(1000);
  Result := '';
end;

// Also remove an update that was downloaded but never installed (it sits beside the folder).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Home, Parent: String;
  Found: TFindRec;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  Home := ExpandConstant('{app}');
  Parent := ExtractFileDir(Home);
  if FindFirst(Parent + '\.' + ExtractFileName(Home) + '.update*', Found) then
  try
    repeat
      DelTree(Parent + '\' + Found.Name, (Found.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0, True, True);
    until not FindNext(Found);
  finally
    FindClose(Found);
  end;
end;
