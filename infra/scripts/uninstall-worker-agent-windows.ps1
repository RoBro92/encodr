param(
    [string]$InstallDir = "C:\ProgramData\EncodrWorker"
)

$ErrorActionPreference = "Stop"

$TaskName = "Encodr Worker Agent"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
}

Write-Host "Encodr worker removed from $InstallDir."
