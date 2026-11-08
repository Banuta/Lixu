@echo off
rem Construieste Lixu.exe (un singur fisier, fara consola) in folderul dist\
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller tinytuya
python -m PyInstaller --noconfirm --onefile --noconsole --name Lixu --add-data "lixu\ui;lixu\ui" --collect-submodules lixu --hidden-import tinytuya lixu_app.py
echo.
echo Gata: dist\Lixu.exe
pause
