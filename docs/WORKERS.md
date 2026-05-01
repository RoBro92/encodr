# Workers

Encodr is the control plane. Workers are execution nodes that run dry-run analysis and processing jobs.

Worker types:

- local worker: runs in the same Docker stack as Encodr
- remote worker: runs as a paired background agent on another host

## Local Worker

The local worker is not assumed to be ready just because Encodr is installed. Add it from the Workers page with `Add this host as worker`.

The local worker uses the stack's `/media` and `/temp` paths. Configure its backend preference, CPU fallback, concurrency, and schedule in Workers.

For Intel hardware, the host and worker container must both see `/dev/dri`. Encodr validates the actual worker runtime before marking an Intel path usable:

- QSV is usable only after an FFmpeg `h264_qsv` smoke encode succeeds.
- VAAPI is a first-class Intel hardware backend and is usable after `vainfo` plus an FFmpeg `h264_vaapi` smoke encode succeeds.
- If Intel auto mode cannot validate QSV but can validate VAAPI, the worker remains healthy and reports `Intel VAAPI active; QSV unavailable: <reason>`.
- If hardware validation fails but CPU fallback is allowed, the worker can stay healthy using CPU. A required backend with fallback disabled is degraded.

## Remote Workers

Remote workers pair from the Workers page with `Add remote worker`. Encodr generates a platform-specific bootstrap command for:

- Windows
- Linux
- macOS

The bootstrap command installs the worker agent, prompts for the pairing token, registers the worker, validates its first heartbeat, clears pairing credentials from the agent environment, and starts a background service.

The default production Compose stack does not start a remote `worker-agent` container or create a fake remote worker. Use `Add remote worker` and run the generated command on the actual worker host. The Compose `worker-agent` service remains available behind the explicit `worker-agent` profile for development and diagnostics.

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
- `intel_auto`: try Intel QSV first, then Intel VAAPI, then CPU if fallback is allowed
- `intel_qsv`: require validated Intel QSV
- `intel_vaapi`: use validated Intel VAAPI; QSV is informational only
- `prefer_intel_igpu`: legacy alias for Intel auto
- `prefer_nvidia_gpu`
- `prefer_amd_gpu`

Run focused Intel diagnostics on the worker host or inside the worker container:

```bash
encodr doctor qsv
```

The diagnostic prints `/dev/dri` visibility, FFmpeg hardware flags, oneVPL/MFX libraries, the VAAPI smoke result, each QSV smoke command attempted, and the backend Encodr would choose next.

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
- The API, local worker compatibility entrypoint, and remote worker-agent still package their runtime code under a top-level `app` module inside separate deployment artifacts. Renaming those packages is deferred because it would touch Docker entrypoints, generated bootstrap commands, service installers, and compatibility imports in one change; import-isolation tests guard the current layout until a coordinated package migration is scheduled.
