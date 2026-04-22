# Deployment

## Current deployment target

- Debian LXC host
- Docker Compose inside the LXC
- Postgres and Redis in the same stack
- API and UI in the initial deployment
- optional local worker in the same stack once explicitly enabled
- `install.sh` for a conservative fresh-LXC bootstrap path
- `encodr` root/operator CLI for local health, update, admin reset, and mount validation

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
