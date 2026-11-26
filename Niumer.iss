; Niumer 安装包脚本（Inno Setup 6）
; 先跑 python build.py 生成 dist\Niumer.exe，再用 ISCC Niumer.iss 编译，
; 产物在 dist\Niumer-Setup-1.1.0.exe。build.py 会自动调用 ISCC（如果装了）。

#define MyAppName "Niumer"
#define MyAppVersion "1.1.8"
#define MyAppPublisher "200Kg"
#define MyAppContact "zwz888123@gmail.com"
#define MyAppExeName "Niumer.exe"

[Setup]
AppId={{5E1D7A4C-9B62-4F0E-8C3D-1A7B2E5F9C41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppContact={#MyAppContact}
AppPublisherURL=mailto:{#MyAppContact}
AppSupportURL=mailto:{#MyAppContact}
VersionInfoVersion=1.1.8.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Niumer 安装程序
VersionInfoProductName={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Niumer-Setup-{#MyAppVersion}
SetupIconFile=logo.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式"
Name: "autostart"; Description: "开机自动启动"; GroupDescription: "其他选项"; Flags: unchecked

[Files]
; onedir 版：把整个运行目录释放到 {app}，启动不再解压 28MB，快很多
Source: "dist\{#MyAppVersion}\runtime\Niumer\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#MyAppVersion}\runtime\Niumer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "Niumer"; ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#MyAppExeName} /F"; \
    Flags: runhidden; RunOnceId: "KillNiumer"

[Code]
{ 覆盖安装时先把正在运行的小条关掉，否则 exe 被占用复制会失败 }
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#MyAppExeName} /F', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
