@echo off
REM Construit dist\NetShift.exe (autonome, sans Python sur le poste cible)
REM et, si Inno Setup 6 est installe, l'installeur dist\NetShift-Setup-<version>.exe
cd /d "%~dp0"
python -m pip install --user pyinstaller -r requirements.txt || (pause & exit /b 1)
python -m PyInstaller --noconfirm --onefile --windowed --uac-admin --name NetShift ^
  --icon assets\netshift.ico --add-data "assets;assets" --collect-all customtkinter --collect-submodules pystray --collect-submodules netshift NetShift.pyw || (pause & exit /b 1)
echo.
echo Executable : dist\NetShift.exe

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 introuvable : installeur non genere ^(https://jrsoftware.org/isdl.php^).
  pause
  exit /b 0
)
for /f %%v in ('python -c "import netshift; print(netshift.__version__)"') do set "VERSION=%%v"
"%ISCC%" /Qp "/DAppVersion=%VERSION%" installer\netshift.iss || (pause & exit /b 1)
echo Installeur : dist\NetShift-Setup-%VERSION%.exe
pause
