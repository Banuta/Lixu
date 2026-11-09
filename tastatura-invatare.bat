@echo off
rem Invatare tastatura: doar citire, nu scrie nimic in tastatura
cd /d "%~dp0"
python -m aicolors kbtest learn
start "" notepad kblearn.txt
pause
