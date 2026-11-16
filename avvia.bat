@echo off
rem Raccolta degli annunci subito, a mano, con la finestra aperta per vedere l'avanzamento.
cd /d "%~dp0"
set "PY=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" -m importhelper
"%PY%" -m importhelper export
start "" "%~dp0site\index.html"
pause
