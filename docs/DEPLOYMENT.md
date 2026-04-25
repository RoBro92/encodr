# Deployment

## Current deployment target

- Debian LXC host
- Docker Compose inside the LXC
- Postgres and Redis in the same stack
- API and UI in the initial deployment
- optional local worker in the same stack once explicitly enabled
- `install.sh` for a conservative fresh-LXC bootstrap path
- `encodr` root/operator CLI for local health, update, admin reset, and mount validation

## Release artifacts

Live release tags publish two artifact types:

- the GitHub release archive used by the installer and `encodr update --apply`
- GHCR images for operators who want pinned images:
  - `ghcr.io/robro92/encodr-api:<tag>`
  - `ghcr.io/robro92/encodr-ui:<tag>`
  - `ghcr.io/robro92/encodr-worker:<tag>`
  - `ghcr.io/robro92/encodr-worker-agent:<tag>`

Stable tags also publish `latest`. Production-like installs should prefer explicit tags such as `v0.3.5`.

## Storage assumptions

- preferred model: mount NFS/SMB on the Proxmox host, then bind-mount into the LXC
- media libraries then bind into Docker from the LXC-visible mount path
- local NVMe used as scratch
- staged outputs verified before final placement
- original file preserved until replacement flow succeeds
- `encodr mount-setup` can validate the LXC-visible target path and print suggested host-side snippets

## Hardware assumptions

- local worker can run in the LXC once explicitly enabled
- Intel iGPU acceleration may be available
- remote workers can register, heartbeat, claim jobs, execute them, and report results
- Windows is the first practical remote worker target

### Intel iGPU passthrough notes

For Intel iGPU passthrough to work truthfully with the local worker:

- the Proxmox host must expose `/dev/dri` into the LXC or VM
- the Encodr worker container must also see `/dev/dri`
- the worker image now includes the required Intel VAAPI userspace runtime packages on Intel-capable Debian targets:
  - `vainfo`
  - `intel-media-va-driver`
  - `libva2`
  - `libva-drm2`
  - `mesa-va-drivers`

Encodr validates Intel against the actual worker runtime by checking:

- `/dev/dri` visibility
- the Intel render node
- `vainfo` availability
- `LIBVA_DRIVER_NAME=iHD vainfo --display drm --device /dev/dri/renderD128`
- an FFmpeg VAAPI smoke test

Expected worker-container validation commands:

```bash
encodr compose-config | grep /dev/dri
docker compose -f docker-compose.yml -f .runtime/compose.runtime.yml exec worker sh -lc 'LIBVA_DRIVER_NAME=iHD vainfo --display drm --device /dev/dri/renderD128'
docker compose -f docker-compose.yml -f .runtime/compose.runtime.yml exec worker sh -lc 'LIBVA_DRIVER_NAME=iHD ffmpeg -hide_banner -vaapi_device /dev/dri/renderD128 -f lavfi -i testsrc2=size=1280x720:rate=30 -t 3 -vf "format=nv12,hwupload" -c:v h264_vaapi -f null -'
```

QSV is not treated as a validated Intel path in this release line unless it gains its own reliable smoke test.

## Required secrets

- `ENCODR_AUTH_SECRET`
- `ENCODR_WORKER_REGISTRATION_SECRET`

These must come from environment configuration in deployed environments.

## Operational notes

- monitor worker/system endpoints and the worker inventory view
- run `encodr doctor` after install, updates, and storage changes
- review `docs/KNOWN_LIMITATIONS.md` before using Encodr on a real media library
- review `docs/WORKERS.md` before enabling the local worker or pairing remote workers
- keep scratch and media mounts distinct
- keep Postgres data backed up before wider internal use
- prefer the first-user setup flow in the UI or `encodr reset-admin` over manual DB edits

## Later deployment work

- broader remote worker rollout to additional host types
- stronger reverse-proxy guidance
- container hardening/slimming
- backup/restore runbooks
