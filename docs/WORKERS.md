# Workers

Encodr is the control plane. Workers are execution nodes that run dry-run analysis and processing jobs.

Worker types:

- local worker: runs in the same Docker stack as Encodr
- remote worker: runs as a paired background agent on another host

## Local Worker

The local worker is not assumed to be ready just because Encodr is installed. Add it from the Workers page with `Add this host as worker`.

The local worker uses the stack's `/media` and `/temp` paths. Configure its backend preference, CPU fallback, concurrency, and schedule in Workers.

For Intel iGPU/VAAPI, the host and worker container must both see `/dev/dri`. Encodr validates the actual worker runtime with `vainfo` and an FFmpeg VAAPI smoke test before marking the Intel path usable.

## Remote Workers

Remote workers pair from the Workers page with `Add remote worker`. Encodr generates a platform-specific bootstrap command for:

- Windows
- Linux
- macOS

The bootstrap command installs the worker agent, stores the server URL and pairing token, registers the worker, validates its first heartbeat, and starts a background service.

Default install locations:

- Windows: `C:\ProgramData\EncodrWorker`
- Linux/macOS: `/opt/encodr-worker`

Windows uses a Scheduled Task. Linux uses `systemd`. macOS uses `launchd`.

## Shared Storage And Path Mappings

Remote execution assumes the worker can access the same media through shared storage. If the server sees a file as `/media/Movies/File.mkv` but the worker sees it as `M:\Movies\File.mkv` or `/mnt/media/Movies/File.mkv`, configure a path mapping on that worker.

Each mapping has:

- server path
- worker path
- optional label
- validation status and message once the worker reports runtime data

Encodr uses these mappings for assignment and execution assumptions. It does not copy full media files to remote workers.

## Backend Preferences

Each worker can set:

- preferred backend
- CPU fallback allowed
- concurrency
- schedule windows
- scratch path
- enabled/disabled state
- display label

Supported backend preferences:

- `cpu_only`
- `prefer_intel_igpu`
- `prefer_nvidia_gpu`
- `prefer_amd_gpu`

Encodr only assigns jobs to workers that are enabled, compatible, and within schedule unless the operator explicitly overrides scheduling for a dry run.

## Dry Runs And Scheduling

Dry runs are background worker jobs. They can be queued, assigned, scheduled, and reviewed like other jobs, but they do not modify media.

Watched jobs can scan source paths, stage or queue new work, and respect ruleset, worker, backend, and schedule preferences. Duplicate prevention is conservative so watched folders do not repeatedly queue the same file.

## Worker States

Worker inventory uses explicit states such as:

- `local_configured_disabled`
- `local_healthy`
- `local_degraded`
- `remote_pending_pairing`
- `remote_registered`
- `remote_healthy`
- `remote_degraded`
- `remote_offline`
- `remote_disabled`

The state should tell you whether the worker exists, whether it is enabled, whether it can take work, and why not.

## Uninstall

Deleting a remote worker in Encodr revokes its server-side token and shows a standalone uninstall command for the target host.

Default uninstall commands:

```bash
sudo /opt/encodr-worker/uninstall-worker-agent.sh
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\EncodrWorker\uninstall-worker-agent.ps1"
```

Run the command on the worker host to remove the local service and files.

## Notes

- Protected files and manual-review items still require explicit operator action.
- Remote workers need reliable network access to the API and shared storage.
- Windows is the most documented remote target; Linux and macOS bootstrap exists, but real-host validation should still be done before relying on them.
