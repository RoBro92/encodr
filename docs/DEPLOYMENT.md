# Deployment

## Primary deployment target

- Debian LXC host
- Docker Compose running inside the LXC
- Postgres and Redis as Compose services
- API, UI, and worker in the same initial stack

## Storage layout assumptions

- media libraries are mounted into the LXC from an NFS share
- local NVMe storage is used as scratch working space for probe and output staging
- processed files return to the original folder by default only after staged-output verification succeeds
- replacement is designed to preserve the original file until the verified output has been placed safely

## Hardware assumptions

- the main worker runs inside the LXC
- Intel iGPU acceleration may be available and should be supported where practical
- remote worker support is a future milestone, not part of the initial deployment

## Operational posture

- internal tool, trusted network, authenticated users
- conservative defaults for file replacement and deletion
- logs and metrics retained long enough for operational review

## Later deployment work

- remote worker support for machines such as an AMD GPU host
- stronger reverse-proxy guidance
- backup and restore guidance for Postgres and configuration
- container hardening and image slimming
