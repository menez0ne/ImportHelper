@echo off
rem Crea o aggiorna l'attività automatica di Windows (raccolta ogni 3 ore e all'accesso).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pianifica.ps1"
pause
