# Workers

Encodr is the control plane. Workers are execution nodes.

There are two worker categories:

- local worker: the same LXC/VM and Docker stack as the Encodr server
- remote workers: separate external machines paired back to Encodr

Remote workers run as service/agent processes. Encodr does not require desktop applications for worker hosts.

## Local worker

The local worker is optional.

Encodr does not treat the current host as a ready worker by default. An operator must explicitly enable it from the Workers page with:

- `Add this host as worker`

When enabled, the local worker:

- runs inside the same Encodr stack/runtime as the server
- uses the same mounted media and scratch paths
- can be enabled or disabled without being forgotten
- has its own preferred backend and CPU fallback policy

### Intel iGPU requirements

Intel iGPU support is now validated conservatively through the worker runtime, not just by checking whether FFmpeg lists encoders.

For Intel VAAPI to be considered usable:

- the LXC or VM must expose `/dev/dri`
- the worker container must also see `/dev/dri`
- the worker image must include the Intel VAAPI userspace runtime packages on Intel-capable Debian targets:
  - `vainfo`
  - `intel-media-va-driver`
  - `libva2`
  - `libva-drm2`
  - `mesa-va-drivers`
- `LIBVA_DRIVER_NAME=iHD vainfo --display drm --device /dev/dri/renderD128` must succeed inside the worker runtime
- a short FFmpeg VAAPI encode smoke test must also succeed inside the worker runtime

Encodr does not depend on `intel-media-va-driver-non-free`.

Expected validation commands inside the worker container:

```bash
encodr compose-config | grep /dev/dri
docker compose -f docker-compose.yml -f .runtime/compose.runtime.yml exec worker sh -lc \
  'LIBVA_DRIVER_NAME=iHD vainfo --display drm --device /dev/dri/renderD128'
docker compose -f docker-compose.yml -f .runtime/compose.runtime.yml exec worker sh -lc \
  'LIBVA_DRIVER_NAME=iHD ffmpeg -hide_banner -vaapi_device /dev/dri/renderD128 -f lavfi -i testsrc2=size=1280x720:rate=30 -t 3 -vf "format=nv12,hwupload" -c:v h264_vaapi -f null -'
```

If Intel VAAPI is not usable, Encodr now surfaces a specific reason such as:

- device missing
- permission denied
- Intel driver missing
- `vainfo` missing
- VAAPI init failed
- FFmpeg VAAPI encode test failed

If the local worker is not configured, the Workers page shows that clearly and the local execution loop does not take jobs.

## Remote workers

Remote workers only appear when they are real:

- pending pairing
- registered
- healthy/degraded/offline
- disabled

Encodr does not create fake remote placeholders.

Use the Workers page action:

- `Add remote worker`

This generates a platform-specific bootstrap command for:

- Windows
- Linux
- macOS

The bootstrap command installs the worker agent, stores the server URL and pairing token, and starts the background service/agent.

## Per-worker backend preference

Backend preference is configured per worker, not as a system-wide worker setting.

Each worker can set:

- preferred backend
- CPU fallback allowed
- enabled/disabled
- display label

Supported backend preferences are:

- `cpu_only`
- `prefer_intel_igpu`
- `prefer_nvidia_gpu`
- `prefer_amd_gpu`

Encodr only advertises and uses hardware paths that are actually present and usable by FFmpeg in that worker's runtime.

For Intel in this release line:

- VAAPI is the validated Intel path
- QSV remains deliberately unverified unless a separate production-grade QSV smoke test is introduced

## Worker states

The UI and API use explicit, truthful worker states. Examples include:

- `local_not_configured`
- `local_configured_disabled`
- `local_healthy`
- `local_degraded`
- `local_unavailable`
- `remote_pending_pairing`
- `remote_registered`
- `remote_healthy`
- `remote_degraded`
- `remote_offline`
- `remote_disabled`

These states are intended to answer:

- is this worker real?
- is it configured?
- can it actually take work?
- if not, why not?

## Notes

- Dry runs remain planning only. They are not worker execution.
- Protected files and manual-review items still follow the same safety rules.
- Assignment remains conservative: only enabled and compatible workers receive work.
- Windows is the first documented remote worker target. Linux/macOS bootstrap generation exists, but wider packaging remains follow-on work.
