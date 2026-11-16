# Crea (o aggiorna) l'attività di Windows "ImportHelper":
# raccolta ogni 3 ore e all'accesso, senza finestre, anche se un turno è stato saltato.
# Per toglierla:  Unregister-ScheduledTask -TaskName ImportHelper -Confirm:$false
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
# Usa l'ambiente .venv creato da installa.bat; se non c'e', il Python di sistema.
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    $python = (Get-Command python.exe).Source
    $pythonw = Join-Path (Split-Path $python) "pythonw.exe"
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m importhelper.background" -WorkingDirectory $root
$every3h = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 3)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logon.Delay = "PT5M"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "ImportHelper" -Action $action -Trigger $every3h, $logon `
    -Settings $settings -Principal $principal -Description "Raccoglie gli annunci e aggiorna site\index.html" -Force | Out-Null
Write-Host "Attività ImportHelper creata: ogni 3 ore e 5 minuti dopo l'accesso. Log: data\ultimo_giro.log"

# Icona "ImportHelper" sul Desktop e nel menu Start: accende il server del sito se serve
# (http://localhost:8765, senza finestre) e apre il sito nel browser.
function Get-BrowserIcon {
    # Icona del browser predefinito (Edge, Chrome, Firefox, Brave...), letta dal registro.
    # Se non si trova (o è un'app dello Store) restituisce $null e si usa l'icona standard.
    try {
        $progId = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice' -ErrorAction Stop).ProgId
        if (-not $progId) { return $null }
        $raw = (Get-ItemProperty "Registry::HKEY_CLASSES_ROOT\$progId\DefaultIcon" -ErrorAction Stop).'(default)'
        if (-not $raw) { return $null }
        $raw = [Environment]::ExpandEnvironmentVariables(($raw -replace '"', '').Trim())
        $path = $raw; $index = 0
        if ($raw -match '^(.*),\s*(-?\d+)$') { $path = $Matches[1].Trim(); $index = $Matches[2] }
        if (Test-Path -LiteralPath $path) { return "$path,$index" }
    } catch {}
    return $null
}
$icon = Get-BrowserIcon
if (-not $icon) { $icon = "$env:SystemRoot\System32\shell32.dll,13" }

$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $ws.CreateShortcut((Join-Path $dir 'ImportHelper.lnk'))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '-m importhelper.open'
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = $icon
    $lnk.Description = 'Apri ImportHelper'
    $lnk.Save()
}
Write-Host "Icona ImportHelper aggiornata sul Desktop e nel menu Start."
