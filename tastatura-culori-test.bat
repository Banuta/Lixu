@echo off
rem Test: poate tastatura sa-si schimbe singura culorile? (pune totul inapoi la final)
cd /d "%~dp0"
python -m aicolors kbtest color
pause
