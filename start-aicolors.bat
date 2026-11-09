@echo off
rem Porneste AI Colors fara consola (pythonw), direct langa ceas
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" /belownormal pythonw -m aicolors app) || (start "" /min /belownormal python -m aicolors app)
