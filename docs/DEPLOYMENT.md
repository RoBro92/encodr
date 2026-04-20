# Deployment

## Current deployment target

- Debian LXC host
- Docker Compose inside the LXC
- Postgres and Redis in the same stack
- API, UI, and local worker in the initial deployment

## Storage assumptions

- media libraries mounted into the LXC from NFS
- local NVMe used as scratch
- staged outputs verified before final placement
- original file preserved until replacement flow succeeds

## Hardware assumptions

- local worker runs in the LXC
- Intel iGPU acceleration may be available
- remote worker registration/heartbeat groundwork is implemented
- remote worker execution is not implemented yet

## Required secrets

- `ENCODR_AUTH_SECRET`
- `ENCODR_WORKER_REGISTRATION_SECRET`

These must come from environment configuration in deployed environments.

## Operational notes

- monitor worker/system endpoints and the worker inventory view
- review `docs/KNOWN_LIMITATIONS.md` before using Encodr on a real media library
- keep scratch and media mounts distinct
- keep Postgres data backed up before wider internal use

## Later deployment work

- remote job assignment to additional hosts
- stronger reverse-proxy guidance
- container hardening/slimming
- backup/restore runbooks
