@echo off
chcp 65001 > nul
rem Toglie l'avvio automatico del sito di ImportHelper (creato da avvio-automatico-server.bat).
rem Il server resta acceso fino al prossimo riavvio; l'icona ImportHelper continua a funzionare.
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ImportHelper server.lnk"
if exist "%LNK%" (
  del "%LNK%"
  echo Fatto: il sito non parte piu' da solo all'accesso. Per aprirlo usa l'icona ImportHelper.
) else (
  echo L'avvio automatico non era attivo: non c'era niente da togliere.
)
pause
