# Deployment

## Target Setup

The primary deployment target is a Debian LXC or Linux VM running Docker Compose. The default stack includes:

- API
- UI
- optional local worker
- Postgres
- Redis

The remote `worker-agent` image is published for hosts that you pair from the Workers page. It is not part of the default production Compose startup; the in-repo service is gated behind the explicit `worker-agent` Compose profile for development or diagnostics.

The host-side `encodr` command handles health checks, updates, admin reset, runtime compose generation, and mount validation.

## Release Artifacts

Tagged releases publish:

- a GitHub release archive used by the installer and `encodr update --apply`
- GHCR images for pinned container deployments:
  - `ghcr.io/robro92/encodr-api:<tag>`
  - `ghcr.io/robro92/encodr-ui:<tag>`
  - `ghcr.io/robro92/encodr-worker:<tag>`
  - `ghcr.io/robro92/encodr-worker-agent:<tag>`

Stable releases also publish `latest`, but live installs should prefer an explicit tag.

## Storage Models

Encodr expects `/media` for the library and `/temp` for scratch inside the stack.

Recommended Proxmox LXC model:

1. Mount NFS or SMB storage on the Proxmox host.
2. Bind-mount that path into the LXC.
3. Let Docker expose the LXC-visible path to Encodr as `/media`.
4. Mount fast scratch storage into the LXC as `/temp`.

Linux VM or direct-host model:

1. Mount the library share with `/etc/fstab` at `/media`.
2. Mount local scratch storage at `/temp`.
3. Start or restart Encodr.

Run this after storage changes:

```bash
encodr mount-setup --validate-only
```

## Hardware

Encodr can expose detected hardware paths through an app-managed runtime Compose override. Regeneration happens during install, start/restart, rebuild, and update flows.

Intel hardware support is validated against the worker runtime before Encodr treats it as usable. Validation checks include `/dev/dri`, `vainfo`, an FFmpeg VAAPI smoke encode, and an FFmpeg QSV smoke encode. VAAPI is a normal Intel hardware backend, not a degraded fallback; QSV is preferred in Intel auto mode only when its oneVPL/QSV smoke test passes.

For Proxmox LXC deployments, pass the Intel render node through to the LXC and then into Docker. A typical host/LXC setup exposes `/dev/dri/renderD128` and the matching `card*` node, then the Encodr runtime override mounts `/dev/dri` into the worker container. The worker image includes `intel-media-va-driver`, `libva2`, `libva-drm2`, `mesa-va-drivers`, `vainfo`, and the available oneVPL/MFX runtime packages, including `libvpl2`, `libmfx-gen1.2`, and `libmfx1` when present in the base distribution.

To inspect the active Compose config:

```bash
encodr compose-config | grep /dev/dri
```

To diagnose Intel QSV and VAAPI from the installed runtime:

```bash
encodr doctor qsv
```

## Reverse Proxy

Encodr is built for a trusted internal network by default. For browser access through a hostname or wider network:

- put it behind a reverse proxy with TLS
- restrict access at the network boundary
- add the hostname with `encodr addhost <fqdn>`
- keep API and UI access authenticated

Do not expose Postgres, Redis, or worker registration endpoints directly to the public internet.

The production Compose file does not publish Postgres or Redis host ports. Use `docker compose exec postgres psql ...` for local administration, or opt into `infra/compose/local.override.yml` during development, which binds those ports to `127.0.0.1` only.

## Required Secrets

Installed environments must have strong values for:

- `POSTGRES_PASSWORD`
- `ENCODR_AUTH_SECRET`
- `ENCODR_WORKER_REGISTRATION_SECRET`

The installer generates these when placeholders are present. If you manage config manually, replace placeholders before running a real deployment.

## Operational Checks

Before using Encodr on a real library:

- run `encodr doctor`
- verify `/media` and `/temp`
- run dry runs on representative files
- confirm worker backend and storage access on the Workers page
- confirm manual review and protected-file behaviour matches your expectations
- back up Postgres before wider use

Review [Workers](./WORKERS.md), [Media policy](./MEDIA_POLICY.md), [Security](./SECURITY.md), and [Known limitations](./KNOWN_LIMITATIONS.md) before processing important media.
