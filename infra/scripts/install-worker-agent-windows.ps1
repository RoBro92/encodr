param(
    [Parameter(Mandatory = $true)][string]$ServerUrl,
    [Parameter(Mandatory = $true)][string]$WorkerKey,
    [string]$PairingToken = "",
    [string]$RegistrationSecret = "",
    [string]$DisplayName = "",
    [string]$InstallDir = "C:\ProgramData\EncodrWorker",
    [string]$Queue = "remote-default",
    [string]$ScratchDir = "C:\EncodrScratch",
    [string]$MediaMounts = "",
    [string]$PythonCommand = "py",
    [string]$ReleaseRef = "main",
    [ValidateSet("cpu", "intel_igpu", "nvidia_gpu", "amd_gpu", "cpu_only", "prefer_intel_igpu", "prefer_nvidia_gpu", "prefer_amd_gpu")]
    [string]$PreferredBackend = "cpu_only",
    [bool]$AllowCpuFallback = $true
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($PairingToken) -and [string]::IsNullOrWhiteSpace($RegistrationSecret)) {
    throw "Provide either -PairingToken or -RegistrationSecret."
}

if ([string]::IsNullOrWhiteSpace($DisplayName)) {
    $DisplayName = $WorkerKey
}

$RepoArchiveUrl =
    if ($ReleaseRef.StartsWith("v")) {
        "https://codeload.github.com/RoBro92/encodr/zip/refs/tags/$ReleaseRef"
    }
    else {
        "https://codeload.github.com/RoBro92/encodr/zip/refs/heads/$ReleaseRef"
    }

$SourceZip = Join-Path $InstallDir "encodr-worker-source.zip"
$SourceRoot = Join-Path $InstallDir "source"
$VenvDir = Join-Path $InstallDir "venv"
$TokenFile = Join-Path $InstallDir "worker.token"
$EnvFile = Join-Path $InstallDir "worker-agent.env.ps1"
$RunScript = Join-Path $InstallDir "run-worker-agent.ps1"
$LogDir = Join-Path $InstallDir "logs"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ScratchDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (Test-Path $SourceRoot) {
    Remove-Item -Recurse -Force $SourceRoot
}

Invoke-WebRequest -UseBasicParsing $RepoArchiveUrl -OutFile $SourceZip
Expand-Archive -Path $SourceZip -DestinationPath $SourceRoot -Force

$ExtractedRoot = Get-ChildItem -Path $SourceRoot -Directory | Select-Object -First 1
if ($null -eq $ExtractedRoot) {
    throw "Unable to locate extracted Encodr source."
}

& $PythonCommand -m venv $VenvDir

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PipExe = Join-Path $VenvDir "Scripts\pip.exe"

& $PipExe install --upgrade pip
& $PipExe install `
    -e (Join-Path $ExtractedRoot.FullName "packages\shared") `
    -e (Join-Path $ExtractedRoot.FullName "packages\core") `
    -e (Join-Path $ExtractedRoot.FullName "apps\worker-agent")

$EnvContents = @"
`$env:ENCODR_WORKER_AGENT_API_BASE_URL = "$ServerUrl"
`$env:ENCODR_WORKER_AGENT_KEY = "$WorkerKey"
`$env:ENCODR_WORKER_AGENT_DISPLAY_NAME = "$DisplayName"
`$env:ENCODR_WORKER_AGENT_QUEUE = "$Queue"
`$env:ENCODR_WORKER_AGENT_SCRATCH_DIR = "$ScratchDir"
`$env:ENCODR_WORKER_AGENT_MEDIA_MOUNTS = "$MediaMounts"
`$env:ENCODR_WORKER_AGENT_TOKEN_FILE = "$TokenFile"
`$env:ENCODR_WORKER_AGENT_FFMPEG_PATH = "ffmpeg"
`$env:ENCODR_WORKER_AGENT_FFPROBE_PATH = "ffprobe"
`$env:ENCODR_WORKER_AGENT_PREFERRED_BACKEND = "$PreferredBackend"
`$env:ENCODR_WORKER_AGENT_ALLOW_CPU_FALLBACK = "$AllowCpuFallback"
`$env:ENCODR_WORKER_AGENT_PAIRING_TOKEN = "$PairingToken"
`$env:ENCODR_WORKER_AGENT_REGISTRATION_SECRET = "$RegistrationSecret"
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
