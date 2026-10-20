@echo off
REM Construit un NetShift.exe autonome (pas besoin de Python sur le poste cible)
cd /d "%~dp0"
python -m pip install --user pyinstaller customtkinter || (pause & exit /b 1)
python -m PyInstaller --noconfirm --onefile --windowed --uac-admin --name NetShift ^
  --icon assets\netshift.ico --add-data "assets;assets" --collect-all customtkinter NetShift.pyw
echo.
echo Termine : dist\NetShift.exe
pause
