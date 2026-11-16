@echo off
rem Doppio clic qui per installare ImportHelper (o per ripararlo: si puo' rilanciare).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installa.ps1"
echo.
pause
