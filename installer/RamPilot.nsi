Unicode True
!ifndef PROJECT_ROOT
 !define PROJECT_ROOT ".."
!endif
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
Name "RamPilot"
OutFile "${PROJECT_ROOT}/dist/RamPilot-Setup-2.1.0.exe"
InstallDir "$LOCALAPPDATA\Programs\RamPilot"
InstallDirRegKey HKCU "Software\RamPilot" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID zlib
ShowInstDetails show
ShowUninstDetails show
BrandingText "RamPilot · CPU Layer Streaming"
VIProductVersion "2.1.0.0"
VIAddVersionKey "ProductName" "RamPilot"
VIAddVersionKey "FileDescription" "RamPilot Windows Installer"
VIAddVersionKey "FileVersion" "2.1.0"
VIAddVersionKey "LegalCopyright" "RamPilot contributors. MIT license."
!define MUI_ICON "${PROJECT_ROOT}/RamPilot.ico"
!define MUI_UNICON "${PROJECT_ROOT}/RamPilot.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Welcome to RamPilot"
!define MUI_WELCOMEPAGE_TEXT "Run local language models on your CPU using system RAM. No GPU, separate Python install, account or API key required.$\r$\n$\r$\nSetup includes the Python and PyTorch CPU engine. Models are read one decoder block at a time. Download SafeTensors weights inside the app or import a compatible model folder.$\r$\n$\r$\nWindows 10/11 x64 with .NET Framework 4.8 is required. If needed, setup installs the included Microsoft Visual C++ runtime, which may request administrator permission."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PROJECT_ROOT}/LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\RamPilot.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open RamPilot"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Function .onInit
 SetShellVarContext current
 SetRegView 64
 ${IfNot} ${RunningX64}
  MessageBox MB_ICONSTOP "RamPilot requires a 64-bit Intel or AMD Windows PC."
  Abort
 ${EndIf}
 ${IfNot} ${AtLeastWin10}
  MessageBox MB_ICONSTOP "RamPilot requires Windows 10 or Windows 11."
  Abort
 ${EndIf}
 ReadRegDWORD $0 HKLM "SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" "Release"
 ${If} $0 < 528040
  MessageBox MB_ICONSTOP "Install Microsoft .NET Framework 4.8, then run setup again.$\r$\n$\r$\nhttps://dotnet.microsoft.com/download/dotnet-framework/net48"
  Abort
 ${EndIf}
 System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\RamPilot.Desktop") p.r0'
 ${If} $0 != 0
  System::Call 'kernel32::CloseHandle(p r0)'
  MessageBox MB_ICONSTOP "Close RamPilot before installing or updating."
  Abort
 ${EndIf}
FunctionEnd
Section "RamPilot" SEC_MAIN
 SectionIn RO
 SetShellVarContext current
 SetRegView 64
 ; Detect the minimum runtime version used by the bundled engine.
 ReadRegDWORD $0 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Installed"
 ReadRegDWORD $1 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Minor"
 ${If} $0 != 1
 ${OrIf} $1 < 44
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "${PROJECT_ROOT}/vendor/vc_redist.x64.exe"
  DetailPrint "Installing Microsoft Visual C++ x64 runtime..."
  ClearErrors
  ExecShellWait "runas" "$PLUGINSDIR\vc_redist.x64.exe" "/install /passive /norestart" SW_SHOWNORMAL $0
  ${If} ${Errors}
   MessageBox MB_ICONSTOP "The Microsoft runtime installation was cancelled or could not start. Setup cannot continue."
   Abort
  ${EndIf}
  ${If} $0 == 3010
   SetRebootFlag true
  ${ElseIf} $0 != 0
  ${AndIf} $0 != 1638
   MessageBox MB_ICONSTOP "Microsoft runtime installation returned code $0. Complete that installation, then run setup again."
   Abort
  ${EndIf}
 ${EndIf}
 SetOutPath "$INSTDIR"
 File "${PROJECT_ROOT}/build/RamPilot.exe"
 File "${PROJECT_ROOT}/build/RamPilot.exe.config"
 File "${PROJECT_ROOT}/catalog.json"
 File "${PROJECT_ROOT}/RamPilot.ico"
 File "${PROJECT_ROOT}/README.txt"
 File "${PROJECT_ROOT}/LICENSE.txt"
 File "${PROJECT_ROOT}/THIRD-PARTY-NOTICES.txt"
 SetOutPath "$INSTDIR\engine"
 File /r /x "*.lib" /x ".*" /x "__pycache__" /x "include" "${PROJECT_ROOT}/build/engine/*"
 SetOutPath "$INSTDIR"
 WriteUninstaller "$INSTDIR\Uninstall.exe"
 CreateDirectory "$SMPROGRAMS\RamPilot"
 CreateShortcut "$SMPROGRAMS\RamPilot\RamPilot.lnk" "$INSTDIR\RamPilot.exe" "" "$INSTDIR\RamPilot.ico"
 CreateShortcut "$SMPROGRAMS\RamPilot\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
 CreateShortcut "$DESKTOP\RamPilot.lnk" "$INSTDIR\RamPilot.exe" "" "$INSTDIR\RamPilot.ico"
 WriteRegStr HKCU "Software\RamPilot" "InstallDir" "$INSTDIR"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "DisplayName" "RamPilot"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "DisplayVersion" "2.1.0"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "Publisher" "RamPilot"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "DisplayIcon" "$INSTDIR\RamPilot.ico"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "InstallLocation" "$INSTDIR"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
 WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "NoModify" 1
 WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot" "NoRepair" 1
SectionEnd
Function un.onInit
 SetShellVarContext current
 SetRegView 64
 System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\RamPilot.Desktop") p.r0'
 ${If} $0 != 0
  System::Call 'kernel32::CloseHandle(p r0)'
  MessageBox MB_ICONSTOP "Close RamPilot before uninstalling."
  Abort
 ${EndIf}
FunctionEnd
Section "Uninstall"
 SetShellVarContext current
 SetRegView 64
 Delete "$INSTDIR\RamPilot.exe"
 Delete "$INSTDIR\RamPilot.exe.config"
 Delete "$INSTDIR\catalog.json"
 Delete "$INSTDIR\RamPilot.ico"
 Delete "$INSTDIR\README.txt"
 Delete "$INSTDIR\LICENSE.txt"
 Delete "$INSTDIR\THIRD-PARTY-NOTICES.txt"
 RMDir /r "$INSTDIR\engine"
 Delete "$INSTDIR\Uninstall.exe"
 RMDir "$INSTDIR"
 Delete "$DESKTOP\RamPilot.lnk"
 Delete "$SMPROGRAMS\RamPilot\RamPilot.lnk"
 Delete "$SMPROGRAMS\RamPilot\Uninstall.lnk"
 RMDir "$SMPROGRAMS\RamPilot"
 DeleteRegKey HKCU "Software\RamPilot"
 DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RamPilot"
 ; Keep downloaded models and conversations. Never silently remove user data.
 IfSilent done
 MessageBox MB_ICONINFORMATION "RamPilot was removed. Models and chats were kept at:$\r$\n$LOCALAPPDATA\RamPilot$\r$\n$\r$\nYou can delete that folder yourself if you no longer need it."
 done:
SectionEnd
