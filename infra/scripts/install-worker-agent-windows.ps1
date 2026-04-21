param(
    [Parameter(Mandatory = $true)][string]$ServerUrl,
    [Parameter(Mandatory = $true)][string]$WorkerKey,
    [Parameter(Mandatory = $true)][string]$RegistrationSecret,
    [string]$DisplayName = "",
    [string]$InstallDir = "C:\ProgramData\EncodrWorker",
    [string]$Queue = "remote-default",
    [string]$ScratchDir = "C:\EncodrScratch",
    [string]$MediaMounts = "",
    [string]$PythonCommand = "py"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DisplayName)) {
    $DisplayName = $WorkerKey
}

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$VenvDir = Join-Path $InstallDir "venv"
$TokenFile = Join-Path $InstallDir "worker.token"
$EnvFile = Join-Path $InstallDir "worker-agent.env.ps1"
$RunScript = Join-Path $InstallDir "run-worker-agent.ps1"
$LogDir = Join-Path $InstallDir "logs"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ScratchDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

& $PythonCommand -m venv $VenvDir

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PipExe = Join-Path $VenvDir "Scripts\pip.exe"

& $PipExe install --upgrade pip
& $PipExe install `
    -e (Join-Path $RepoRoot "packages\shared") `
    -e (Join-Path $RepoRoot "packages\core") `
    -e (Join-Path $RepoRoot "apps\worker-agent")

$EnvContents = @"
`$env:ENCODR_WORKER_AGENT_API_BASE_URL = "$ServerUrl"
`$env:ENCODR_WORKER_AGENT_KEY = "$WorkerKey"
`$env:ENCODR_WORKER_AGENT_DISPLAY_NAME = "$DisplayName"
`$env:ENCODR_WORKER_AGENT_REGISTRATION_SECRET = "$RegistrationSecret"
`$env:ENCODR_WORKER_AGENT_QUEUE = "$Queue"
`$env:ENCODR_WORKER_AGENT_SCRATCH_DIR = "$ScratchDir"
`$env:ENCODR_WORKER_AGENT_MEDIA_MOUNTS = "$MediaMounts"
`$env:ENCODR_WORKER_AGENT_TOKEN_FILE = "$TokenFile"
`$env:ENCODR_WORKER_AGENT_FFMPEG_PATH = "ffmpeg"
`$env:ENCODR_WORKER_AGENT_FFPROBE_PATH = "ffprobe"
"@
$EnvContents | Set-Content -Path $EnvFile -Encoding UTF8

$RunContents = @"
. "$EnvFile"
& "$PythonExe" -m app.main loop 999999
"@
$RunContents | Set-Content -Path $RunScript -Encoding UTF8

$TaskName = "Encodr Worker Agent"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`""
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Encodr Windows worker installed."
Write-Host "Task name: $TaskName"
Write-Host "Worker key: $WorkerKey"
Write-Host "Server URL: $ServerUrl"
