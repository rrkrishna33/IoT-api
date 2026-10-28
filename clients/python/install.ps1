#Requires -RunAsAdministrator
<#
Installs the IoT agent on a Windows customer PC. Run from the folder that holds
agent.py, readers.py, iot_client.py and this script, in an elevated PowerShell:

  powershell -ExecutionPolicy Bypass -File .\install.ps1 -ConfigPath C:\path\to\config-acme.json

What it does: copies the agent to C:\IoTAgent, creates a private Python venv with
`requests`, installs the config (readable only by SYSTEM and Administrators), sends
one test cycle, then registers a Scheduled Task that starts at boot, restarts on
failure, and runs without anyone logged in. Safe to re-run with -Force.
#>
param(
    [Parameter(Mandatory)] [string]$ConfigPath,
    [string]$InstallDir = "C:\IoTAgent",
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$TaskName = "IoTAgent"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

Step "Checking files"
foreach ($f in "agent.py", "readers.py", "iot_client.py") {
    if (-not (Test-Path (Join-Path $here $f))) { throw "Missing $f next to install.ps1" }
}
if (-not (Test-Path $ConfigPath)) { throw "Config file not found: $ConfigPath" }
$cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
if (-not $cfg.printers -or $cfg.printers.Count -eq 0) { throw "Config has no printers" }
if ($cfg.printers | Where-Object { $_.reader.type -eq "simulated" }) {
    Write-Warning "Some printers still use the 'simulated' reader: they will send FAKE numbers."
}
if ($cfg.queue_dir -and -not $cfg.queue_dir.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Warning "queue_dir ($($cfg.queue_dir)) is outside $InstallDir; make sure SYSTEM can write there."
}

Step "Checking Python (3.9+)"
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "Python not found. Install Python 3.9+ from python.org (tick 'Add to PATH'), then re-run." }
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.9 or newer is required." }

$dest = Join-Path $InstallDir "config.json"
if ((Test-Path $dest) -and -not $Force) { throw "$dest already exists. Re-run with -Force to replace it (the old keys would be overwritten)." }

Step "Stopping any previous install"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Step "Copying files to $InstallDir"
New-Item -ItemType Directory -Force $InstallDir | Out-Null
foreach ($f in "agent.py", "readers.py", "iot_client.py") { Copy-Item (Join-Path $here $f) $InstallDir -Force }

Step "Installing config (restricted to SYSTEM and Administrators)"
Copy-Item $ConfigPath $dest -Force
icacls $dest /inheritance:r /grant:r "SYSTEM:(R)" "Administrators:(F)" | Out-Null

Step "Creating private Python environment"
$venv = Join-Path $InstallDir "venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) { & $py -m venv $venv; if ($LASTEXITCODE) { throw "venv creation failed" } }
$vpy = Join-Path $venv "Scripts\python.exe"
& $vpy -m pip install --quiet --disable-pip-version-check requests
if ($LASTEXITCODE) { throw "pip install requests failed (is the PC online?)" }

Step "Test run (reads every printer and sends one reading each)"
& $vpy (Join-Path $InstallDir "agent.py") $dest --once
if ($LASTEXITCODE -ne 0) { throw "Test run failed (exit $LASTEXITCODE). Fix the config or connectivity, then re-run. Nothing was scheduled." }

Step "Registering scheduled task '$TaskName'"
$action   = New-ScheduledTaskAction -Execute $vpy -Argument "`"$InstallDir\agent.py`" `"$dest`"" -WorkingDirectory $InstallDir
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -User "SYSTEM" -RunLevel Highest | Out-Null
Start-ScheduledTask -TaskName $TaskName

Step "Done"
Start-Sleep -Seconds 5
Write-Host "Task state: $((Get-ScheduledTask -TaskName $TaskName).State)"
$log = $cfg.log_path
if ($log -and (Test-Path $log)) { Write-Host "Last log lines ($log):"; Get-Content $log -Tail 5 }
Write-Host "`nInstalled. It starts at boot and keeps running. To remove it: .\uninstall.ps1"
