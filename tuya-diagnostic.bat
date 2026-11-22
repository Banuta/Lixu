@echo off
rem Diagnostic pentru becul Tuya: scrie tuya-diagnostic.txt in folderul asta (fara cheie)
cd /d "%~dp0"
echo Becul trebuie sa fie aprins de la intrerupator. Inchide aplicatia Smart Life de pe telefon.
echo Inchide si AI Colors (de langa ceas - Iesire), ca sa nu tina el conexiunea cu becul.
echo Dureaza cam 1 minut. La final becul se face rosu, apoi verde.
echo.
python -m aicolors tuyadiag
if errorlevel 1 (
  echo.
  echo Nu merge comanda python. Instaleaza Python de pe python.org si bifeaza "Add python.exe to PATH".
)
start "" notepad tuya-diagnostic.txt
pause
