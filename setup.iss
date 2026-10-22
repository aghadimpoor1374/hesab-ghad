#ifndef TargetArch
  #define TargetArch "x64"
#endif
[Setup]
AppId=HesabGhadimDesktop
AppName=Hesab Ghadim
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\HesabGhadim
DefaultGroupName=Hesab Ghadim
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=HesabGhadim-Setup-Win8plus-{#TargetArch}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=source\assets\app-icon.ico
MinVersion=6.2
#if TargetArch == "x64"
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
#endif
UninstallDisplayIcon={app}\HesabGhadim.exe
[Files]
Source: "source\dist\HesabGhadim\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Hesab Ghadim"; Filename: "{app}\HesabGhadim.exe"
Name: "{userdesktop}\Hesab Ghadim"; Filename: "{app}\HesabGhadim.exe"
[Run]
Filename: "{app}\HesabGhadim.exe"; Description: "Launch Hesab Ghadim"; Flags: nowait postinstall skipifsilent
