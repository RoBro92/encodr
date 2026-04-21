# Windows Worker Setup

This is the first supported remote-worker target for Encodr.

The Windows worker has no local UI. It is installed as a background agent that:

- registers with the Encodr server
- heartbeats
- polls for assigned work
- claims jobs
- executes them locally
- reports the final result back to the Encodr server

## Requirements

- Windows host with Python 3.12+
- `ffmpeg` and `ffprobe` available on `PATH`
- access to the same media storage paths that the Encodr plan expects
- a writable scratch path
- the Encodr worker registration secret from the server

## Install from a checked-out Encodr release

From an elevated PowerShell session in the extracted Encodr release directory:

```powershell
.\infra\scripts\install-worker-agent-windows.ps1 `
  -ServerUrl "https://encodr.example.com/api" `
  -WorkerKey "windows-qsv-01" `
  -DisplayName "Windows QSV Worker" `
  -RegistrationSecret "<worker-registration-secret>" `
  -Queue "remote-default" `
  -ScratchDir "D:\EncodrScratch" `
  -MediaMounts "M:\Media"
```

The script will:

- create a dedicated virtual environment
- install `encodr-shared`, `encodr-core`, and `encodr-worker-agent`
- write the worker environment file
- create a Windows Scheduled Task called `Encodr Worker Agent`
- start the worker immediately

## What the worker stores locally

Under `C:\ProgramData\EncodrWorker` by default:

- `venv\`
- `worker.token`
- `worker-agent.env.ps1`
- `run-worker-agent.ps1`

The worker token is issued by the Encodr server during registration.

## Operational notes

- If `ffmpeg` or `ffprobe` is not available, the worker will report itself as failed and will not claim jobs.
- If the scratch path is not writable, the worker will report degraded/failed health and will not claim jobs safely.
- Capability reporting is intentionally conservative. Encodr only advertises Intel QSV when the worker can really initialise it.

## Updating a worker

Re-run the install script from an updated Encodr release checkout. The Scheduled Task is recreated in place.
