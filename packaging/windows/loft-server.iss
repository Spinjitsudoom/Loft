; The Loft server's setup for Windows (Inno Setup 6). packaging/build_server.py compiles it with:
;   ISCC /DAppVersion=x.y.z /DSourceDir=<built loft-server folder> /DOutputDir=<dist>
;        /DOutputName=<file name, no .exe> /DIconFile=<loft.ico> loft-server.iss
;
; It installs for the person running it (no administrator needed) into
; %LOCALAPPDATA%\Programs\Loft Server, a folder Loft may write to, so it can update itself: the
; server downloads the next setup and runs it silently (src/loft/updates.py). Loft's own data stays
; in %LOCALAPPDATA%\Loft and is never touched, by installing or by uninstalling.

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
UninstallDisplayIcon={app}\loft-server.exe
UninstallDisplayName=Loft Server
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; A running Loft is stopped so its files can be replaced; the last page starts it again.
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "startup"; Description: "Start Loft Server when I sign in to Windows"
Name: "desktopicon"; Description: "Put an ""Open Loft"" shortcut on the desktop"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Files a newer version no longer has.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Loft Server"; Filename: "{app}\loft-server.exe"; WorkingDir: "{app}"; Comment: "Start the Loft server"
Name: "{autoprograms}\Open Loft"; Filename: "http://localhost:4545"; IconFilename: "{app}\loft-server.exe"; Comment: "Open Loft in your browser"
Name: "{autodesktop}\Open Loft"; Filename: "http://localhost:4545"; IconFilename: "{app}\loft-server.exe"; Tasks: desktopicon
Name: "{userstartup}\Loft Server"; Filename: "{app}\loft-server.exe"; WorkingDir: "{app}"; Flags: runminimized; Tasks: startup

[Run]
Filename: "{app}\loft-server.exe"; WorkingDir: "{app}"; Description: "Start Loft Server now"; Flags: nowait postinstall skipifsilent
Filename: "{app}\README.txt"; Description: "Show how to use it"; Flags: shellexec nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM loft-server.exe"; Flags: runhidden; RunOnceId: "StopLoft"

[Code]
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
