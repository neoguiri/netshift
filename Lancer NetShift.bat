@echo off
cd /d "%~dp0"
where python >nul 2>nul || (
  echo Python est introuvable. Installe-le depuis https://www.python.org ^(cocher "Add to PATH"^).
  pause
  exit /b 1
)
python -c "import customtkinter, pystray, PIL" >nul 2>nul || (
  echo Installation des dependances...
  python -m pip install --user -r requirements.txt || (pause & exit /b 1)
)
start "" pythonw "%~dp0NetShift.pyw"
