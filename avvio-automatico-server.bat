@echo off
chcp 65001 > nul
rem Fa partire il sito di ImportHelper (http://localhost:8765) da solo all'accesso a Windows,
rem senza finestre: mette un collegamento nella cartella "Esecuzione automatica" e accende subito il server.
rem Per toglierlo: disattiva-avvio-automatico-server.bat
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  set "PYW=%~dp0.venv\Scripts\pythonw.exe"
  goto :have
)
for /f "delims=" %%P in ('where python') do (set "PY=%%P" & goto :found)
echo Python non trovato: fai prima doppio clic su installa.bat.
pause
exit /b 1
:found
set "PYW=%PY:python.exe=pythonw.exe%"
:have
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'ImportHelper server.lnk'));" ^
  "$lnk.TargetPath = '%PYW%'; $lnk.Arguments = '-m importhelper.server'; $lnk.WorkingDirectory = '%~dp0';" ^
  "$lnk.WindowStyle = 7; $lnk.Description = 'Sito di ImportHelper su http://localhost:8765'; $lnk.Save()"
if errorlevel 1 (
  echo Non sono riuscito a creare l'avvio automatico.
  pause
  exit /b 1
)
start "" "%PYW%" -m importhelper.server
echo Fatto: il sito http://localhost:8765 ora parte da solo a ogni accesso a Windows.
echo Il server e' gia' acceso: puoi usare il segnalibro del browser.
pause
