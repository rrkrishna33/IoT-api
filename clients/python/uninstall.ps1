#Requires -RunAsAdministrator
<#
Removes the IoT agent from this PC: stops and deletes the scheduled task, and with
-RemoveFiles also deletes the install folder (config with device keys, queue, logs).
Unsent queued readings are lost if you remove the files.
#>
param(
    [string]$InstallDir = "C:\IoTAgent",
    [switch]$RemoveFiles
)
$TaskName = "IoTAgent"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task $TaskName"
} else {
    Write-Host "No scheduled task named $TaskName"
}
if ($RemoveFiles) {
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir; Write-Host "Deleted $InstallDir" }
} else {
    Write-Host "Files left in $InstallDir (re-run with -RemoveFiles to delete the config, queue and logs)."
}
Write-Host "Also revoke this PC's device keys on the server if it is being retired."
