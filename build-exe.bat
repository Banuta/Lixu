@echo off
rem Construieste AIColors.exe (un singur fisier, fara consola) in folderul dist\
rem Include tot: Tuya (tinytuya + cryptography), interfata, Logitech fara G HUB.
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install --upgrade pyinstaller .
if errorlevel 1 (
  echo Instalarea dependintelor a esuat. Trimite-mi textul de mai sus.
  pause
  exit /b 1
)
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name AIColors --icon "aicolors\ui\aicolors.ico" ^
  --add-data "aicolors\ui;aicolors\ui" ^
  --collect-submodules aicolors ^
  --collect-all tinytuya ^
  --collect-submodules cryptography ^
  --hidden-import requests --hidden-import colorama ^
  aicolors_app.py
echo.
echo Gata: dist\AIColors.exe
pause
