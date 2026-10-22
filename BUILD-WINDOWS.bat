@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .build-env
if errorlevel 1 goto fail
.build-env\Scripts\python -m pip install -r source\requirements.txt pyinstaller
if errorlevel 1 goto fail
cd source
..\.build-env\Scripts\python -m PyInstaller --noconfirm --clean --windowed --onedir --name HesabGhadim --icon assets/app-icon.ico --collect-all reportlab --collect-all arabic_reshaper --collect-all bidi --add-data "assets;assets" --add-data "license-public.key;." --add-data "update-public.key;." windows_entry.py
if errorlevel 1 goto fail
cd ..
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
 echo Install Inno Setup 6 from https://jrsoftware.org/isdl.php then run this file again.
 pause
 exit /b 1
)
"%ISCC%" setup.iss
if errorlevel 1 goto fail
echo SUCCESS: output\HesabGhadim-Setup-Win10.exe
pause
exit /b 0
:fail
echo BUILD FAILED. Please save the error above.
pause
exit /b 1
