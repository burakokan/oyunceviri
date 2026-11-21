; Setup for Oyun Çeviri: packaging\build.bat makes dist\OyunCeviri with PyInstaller, then this script
; turns it into output\OyunCeviri-Kurulum.exe. Installs for the current user only (no admin needed), into a
; folder the app can write to (config.json, logs, packs). Personal use only.

; The version comes from pc\gt\version.py: publish.py passes it as /DAppVersion=...
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define Repo "https://github.com/burakokan/oyunceviri"

[Setup]
AppId={{8C6F2B8E-5D1A-4C1E-9E33-0A7B3E2C9F11}
AppName=Oyun Çeviri
AppVersion={#AppVersion}
AppVerName=Oyun Çeviri {#AppVersion}
AppPublisher=Oyun Çeviri
AppPublisherURL={#Repo}
AppUpdatesURL={#Repo}/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Oyun Çeviri
VersionInfoDescription=Oyun Çeviri kurulumu
DefaultDirName={localappdata}\Programs\Oyun Ceviri
DefaultGroupName=Oyun Çeviri
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=OyunCeviri-Kurulum
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\OyunCeviri.exe
UninstallDisplayName=Oyun Çeviri
Compression=lzma2/normal
SolidCompression=no
DiskSpanning=yes
; Each part stays under 2 GB: GitHub Releases takes files up to 2 GiB.
DiskSliceSize=1900000000
WizardStyle=modern
; Pictures from make_wizard.py (100 / 150 / 200 % screen scaling)
WizardImageFile=wizard\side-100.bmp,wizard\side-150.bmp,wizard\side-200.bmp
WizardSmallImageFile=wizard\small-100.bmp,wizard\small-150.bmp,wizard\small-200.bmp
WizardImageStretch=no
WizardImageBackColor=$120D0A
ShowLanguageDialog=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne kısayol koy"
Name: "firewall"; Description: "TV'nin bu bilgisayara bağlanabilmesi için Windows güvenlik duvarında izin ver (önerilir, bir kez yönetici onayı ister)"

[Files]
Source: "dist\OyunCeviri\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Oyun Çeviri"; Filename: "{app}\OyunCeviri.exe"
Name: "{autodesktop}\Oyun Çeviri"; Filename: "{app}\OyunCeviri.exe"; Tasks: desktopicon

[Run]
; Inbound permission for the TV connection (port 8765), on every network type: home networks are often "Public".
Filename: "{cmd}"; Parameters: "/c netsh advfirewall firewall delete rule name=""Oyun Ceviri"" >nul & netsh advfirewall firewall add rule name=""Oyun Ceviri"" dir=in action=allow program=""{app}\OyunCeviri.exe"" enable=yes profile=any"; Flags: runhidden shellexec waituntilterminated; Verb: runas; Tasks: firewall; StatusMsg: "Güvenlik duvarı izni veriliyor…"
Filename: "{app}\OyunCeviri.exe"; Description: "Oyun Çeviri'yi şimdi aç"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c netsh advfirewall firewall delete rule name=""Oyun Ceviri"""; Flags: runhidden shellexec; Verb: runas; RunOnceId: "fw"; Tasks: firewall

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\packs\build"
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\ps5.json"
Type: files; Name: "{app}\speakers.json"
Type: files; Name: "{app}\speaker_game_colors.json"
Type: files; Name: "{app}\region_cache.json"
Type: files; Name: "{app}\screen_cache.json"
Type: filesandordirs; Name: "{app}\tv-keys"
Type: filesandordirs; Name: "{app}\update"

[Code]
// Files that in-place updates added (listed in update\files.txt) are unknown to the uninstaller: remove them too.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Lines: TArrayOfString;
  I: Integer;
  Name: String;
begin
  if CurUninstallStep = usUninstall then
    if LoadStringsFromFile(ExpandConstant('{app}\update\files.txt'), Lines) then
      for I := 0 to GetArrayLength(Lines) - 1 do
      begin
        Name := Trim(Lines[I]);
        StringChangeEx(Name, '/', '\', True);
        if (Name <> '') and (Pos('..', Name) = 0) then
          DeleteFile(ExpandConstant('{app}\') + Name);
      end;
end;
