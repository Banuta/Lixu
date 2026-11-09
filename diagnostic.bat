@echo off
rem Diagnostic AI Colors: scrie diagnostic.txt in folderul asta
cd /d "%~dp0"
echo Tastatura trebuie sa fie pe cablu, iar aplicatia ZENKABEAT inchisa (si din tray).
echo Uita-te la tastatura: o sa incerce rosu, verde, albastru.
echo.
python -m aicolors diag
if errorlevel 1 (
  echo.
  echo Nu merge comanda python. Instaleaza Python de pe python.org si bifeaza "Add python.exe to PATH".
)
start "" notepad diagnostic.txt
pause
