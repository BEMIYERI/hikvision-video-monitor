# ============================================================
#  HIKVISION VIDEO MONITOR - installation sur serveur Windows
#  A executer en PowerShell EN ADMINISTRATEUR, dans le dossier
#  extrait (clic droit sur ce fichier -> Executer avec PowerShell).
#  Relancer le script est sans danger (idempotent).
# ============================================================
#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$dst = 'C:\hikvision-monitor'

function Etape($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "  [OK] $t" -ForegroundColor Green }
function Ko($t)    { Write-Host "  [!!] $t" -ForegroundColor Yellow }

Etape "1/6  Copie du projet vers $dst"
if ((Resolve-Path $src).Path.TrimEnd('\') -ne $dst) {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item -Path (Join-Path $src '*') -Destination $dst -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $dst 'logs')   | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dst 'reports')| Out-Null
Ok "projet en place dans $dst"

Etape "2/6  Recherche d'un Python 3.10 ou plus recent"
$essais = @()
if (Get-Command py     -ErrorAction SilentlyContinue) { $essais += ,@('py','-3') }
if (Get-Command python -ErrorAction SilentlyContinue) { $essais += ,@('python') }
foreach ($c in @("$env:LOCALAPPDATA\Python\PythonCore-3.14-64\python.exe",
                 "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                 "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                 'C:\Python312\python.exe','C:\Python311\python.exe','C:\Python310\python.exe')) {
    if (Test-Path $c) { $essais += ,@($c) }
}
$pythonExe = $null
$pythonPre = @()
foreach ($e in $essais) {
    $exe = $e[0]
    if ($e.Count -gt 1) { $pythonPre = $e[1..($e.Count-1)] } else { $pythonPre = @() }
    try {
        $v = & $exe @pythonPre -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) {
            $parts = $v.Trim().Split('.')
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
                $pythonExe = $exe
                Ok "Python $v  ->  $exe $($pythonPre -join ' ')"
                break
            }
            Ko "Python $v trop ancien ($exe) : 3.10 minimum"
        }
    } catch { }
}
if (-not $pythonExe) {
    Ko "aucun Python 3.10+ trouve sur ce serveur"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  installation via winget..."
        winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
        Write-Host ""
        Ko "relancez ce script une fois l'installation terminee"
    } else {
        Write-Host "  Installez Python 3.12 depuis https://www.python.org/downloads/windows/"
        Write-Host "  (cochez 'Add python.exe to PATH'), puis relancez ce script."
    }
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}

Etape "3/6  Environnement virtuel et dependances"
$venv = Join-Path $dst '.venv'
$vpy  = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    & $pythonExe @pythonPre -m venv $venv
    if (-not (Test-Path $vpy)) { Ko "creation du venv impossible"; Read-Host; exit 1 }
}
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r (Join-Path $dst 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) { Ko "echec de pip install"; Read-Host; exit 1 }
Ok "requests, openpyxl, python-dotenv installes dans $venv"

Etape "4/6  Configuration"
$envFile = Join-Path $dst 'config\.env'
if (-not (Test-Path $envFile)) {
    Ko "config\.env absent : l'archive doit le contenir"
    Read-Host "Appuyez sur Entree pour fermer"; exit 1
}
$lignes = @(Get-Content $envFile -Encoding UTF8)
$trouve = $false
$lignes = $lignes | ForEach-Object {
    if ($_ -match '^\s*DASHBOARD_HOST\s*=') { $trouve = $true; 'DASHBOARD_HOST=127.0.0.1' } else { $_ }
}
if (-not $trouve) { $lignes += 'DASHBOARD_HOST=127.0.0.1' }
Set-Content -Path $envFile -Value $lignes -Encoding UTF8
Ok "DASHBOARD_HOST=127.0.0.1 : rien d'expose sur le reseau du site (acces par Tailscale)"

Etape "5/6  TEST DECISIF - collecte des 5 NVR"
Push-Location $dst
& $vpy 'src\main.py' --once | Out-Host
$code = $LASTEXITCODE
Pop-Location
if ($code -eq 0) { Ok "NVR joignables depuis ce serveur" }
else { Ko "code $code : au moins un NVR injoignable - relisez le resume ci-dessus" }

Etape "6/6  Demarrage automatique au boot"
$cmdFile = Join-Path $dst 'run_monitor.cmd'
$cmd = "@echo off`r`ncd /d `"%~dp0`"`r`n`".venv\Scripts\python.exe`" `"src\main.py`" >> `"logs\service.log`" 2>&1`r`n"
Set-Content -Path $cmdFile -Value $cmd -Encoding ASCII -NoNewline
$act = New-ScheduledTaskAction -Execute $cmdFile -WorkingDirectory $dst
$trg = New-ScheduledTaskTrigger -AtStartup
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$prn = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'Hikvision Monitor' -Action $act -Trigger $trg `
        -Settings $set -Principal $prn -Force | Out-Null
Start-ScheduledTask -TaskName 'Hikvision Monitor'
Ok "tache 'Hikvision Monitor' : au demarrage, compte SYSTEM, redemarrage auto"

Start-Sleep -Seconds 10
$ecoute = (Test-NetConnection -ComputerName 127.0.0.1 -Port 8765 -WarningAction SilentlyContinue).TcpTestSucceeded
if ($ecoute) { Ok "dashboard actif sur http://127.0.0.1:8765" } else { Ko "dashboard non joignable - voir logs\monitor.log" }

$ts = 'C:\Program Files\Tailscale\tailscale.exe'
if ((Test-Path $ts) -and $ecoute) {
    Write-Host ""
    Write-Host "  configuration de l'acces HTTPS Tailscale..." -ForegroundColor Cyan
    & $ts serve --bg --https=443 http://127.0.0.1:8765 2>&1 | Out-Host
}

$nomTs = (& $ts status --json 2>$null | ConvertFrom-Json).Self.DNSName
Write-Host ""
Write-Host "================= TERMINE =================" -ForegroundColor Green
Write-Host "  Local (sur le serveur) : http://127.0.0.1:8765"
if ($nomTs) { Write-Host "  Tailscale              : https://$($nomTs.TrimEnd('.'))" }
Write-Host ""
Write-Host "  Journal    : $dst\logs\monitor.log"
Write-Host "  Arreter    : Stop-ScheduledTask -TaskName 'Hikvision Monitor'"
Write-Host "  Desinstaller : Unregister-ScheduledTask -TaskName 'Hikvision Monitor' -Confirm:`$false"
Read-Host "Appuyez sur Entree pour fermer"
