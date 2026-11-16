# Installazione di ImportHelper: si lancia con doppio clic su installa.bat.
# Si puo' rilanciare quando si vuole (es. dopo aver spostato la cartella): rifa' solo quello che serve.
#  1. trova Python 3.10+ (se manca lo installa con winget, solo per questo utente)
#  2. crea l'ambiente .venv nella cartella e installa le librerie
#  3. crea la raccolta automatica ogni 3 ore e l'icona ImportHelper (pianifica.ps1)
#  4. apre il sito
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) {
    Write-Host ""
    Write-Host "PROBLEMA: $text" -ForegroundColor Red
    Write-Host "Manda una foto di questa finestra a chi ti ha passato ImportHelper."
    exit 1
}

function Find-Python {
    # Restituisce il percorso di un python.exe 3.10 o piu' recente, oppure $null.
    $candidates = @()
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $p = & py.exe -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $p) { $candidates += "$p".Trim() }
    }
    foreach ($c in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        # quello in WindowsApps e' solo un collegamento al Microsoft Store
        if ($c.Source -notlike "*WindowsApps*") { $candidates += $c.Source }
    }
    $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                                   "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
                     Sort-Object FullName -Descending | ForEach-Object { $_.FullName })
    foreach ($p in $candidates) {
        $ok = & $p -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
        if ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq "True") { return $p }
    }
    return $null
}

Write-Host "Installazione di ImportHelper in $root" -ForegroundColor Green

# I file scaricati da Internet sono "bloccati" da Windows: li sblocchiamo per non avere avvisi a ogni avvio.
Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

# --- 1. Python ---------------------------------------------------------------------------
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$venvOk = $false
if (Test-Path $venvPy) {
    & $venvPy -c "import requests" 2>$null
    $venvOk = ($LASTEXITCODE -eq 0)
}

if (-not $venvOk) {
    Step "Cerco Python"
    $py = Find-Python
    if (-not $py) {
        if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
            Step "Python non c'e': lo installo (ci vuole qualche minuto, se Windows chiede conferma rispondi Si')"
            winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            $py = Find-Python
        }
    }
    if (-not $py) {
        Start-Process "https://www.python.org/downloads/"
        Fail ("Non trovo Python e non sono riuscito a installarlo da solo.`n" +
              "Si e' aperta la pagina di download: scarica Python, durante l'installazione spunta`n" +
              "'Add python.exe to PATH', poi rifai doppio clic su installa.bat.")
    }
    Write-Host "Uso $py"

    # --- 2. ambiente .venv e librerie -------------------------------------------------------
    Step "Preparo l'ambiente di ImportHelper (cartella .venv)"
    if (Test-Path (Join-Path $root ".venv")) { Remove-Item -Recurse -Force (Join-Path $root ".venv") }
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Fail "Non sono riuscito a creare la cartella .venv." }
}

Step "Installo le librerie necessarie"
& $venvPy -m pip install --disable-pip-version-check --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "Installazione delle librerie non riuscita. Controlla di essere connesso a Internet e riprova." }

# --- 3. raccolta automatica e icona --------------------------------------------------------
Step "Creo la raccolta automatica (ogni 3 ore) e l'icona ImportHelper sul Desktop"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "pianifica.ps1")
if ($LASTEXITCODE -ne 0) { Fail "Non sono riuscito a creare l'attivita' automatica o l'icona." }

# --- 4. fatto ------------------------------------------------------------------------------
Write-Host ""
Write-Host "FATTO! ImportHelper e' installato." -ForegroundColor Green
Write-Host "- Per aprirlo usa l'icona ImportHelper sul Desktop (o nel menu Start)."
Write-Host "- La prima raccolta degli annunci parte da sola tra 5 minuti e dura un po'."
Write-Host "  Nel frattempo puoi gia' usare 'Cerca un'auto' nel sito."
Write-Host "- Non spostare ne' rinominare questa cartella (se lo fai, rilancia installa.bat)."
Write-Host ""
Write-Host "Apro il sito..."
Start-Process -FilePath (Join-Path $root ".venv\Scripts\pythonw.exe") -ArgumentList "-m importhelper.open" -WorkingDirectory $root
exit 0
