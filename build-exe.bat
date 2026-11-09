@echo off
rem Construieste AIColors.exe (un singur fisier, fara consola) in folderul dist\
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller tinytuya
python -m PyInstaller --noconfirm --onefile --noconsole --name AIColors --add-data "aicolors\ui;aicolors\ui" --collect-submodules aicolors --hidden-import tinytuya aicolors_app.py
echo.
echo Gata: dist\AIColors.exe
pause
