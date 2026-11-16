@echo off
chcp 65001 > nul
rem Toglie la raccolta automatica, le icone e l'avvio automatico del sito.
rem Dopo puoi cancellare questa cartella (con dentro annunci e ricerche).
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Unregister-ScheduledTask -TaskName ImportHelper -Confirm:$false -ErrorAction SilentlyContinue;" ^
  "foreach ($f in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { Remove-Item (Join-Path $f 'ImportHelper.lnk') -ErrorAction SilentlyContinue };" ^
  "Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'ImportHelper server.lnk') -ErrorAction SilentlyContinue"
echo Fatto: niente piu' raccolta automatica ne' icone.
echo Riavvia il PC (per spegnere il server del sito), poi puoi cancellare questa cartella.
pause
