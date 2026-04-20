# Encodr

Encodr is a private, self-hosted media preparation service for Plex-style libraries. It inspects files with `ffprobe`, applies deterministic policy, and then safely skips, remuxes, transcodes, or sends a file to manual review before placing the verified result back into your library.

It is designed for people who want a conservative, auditable workflow rather than a broad automation platform.

## What Encodr does

- scans and inspects media files before ingestion
- applies policy-driven decisions from YAML managed by the app install
- treats 4K content conservatively by default
- keeps English audio and subtitles, including forced English subtitles
- preserves surround and Atmos-capable audio where possible
- verifies staged outputs before they are treated as successful
- keeps a history of probe, plan, job, review, audit, and analytics data
- provides a web UI for jobs, files, reports, manual review, worker status, and storage health

## Recommended install

Run this inside your Debian LXC or Linux VM:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | sudo bash
```

The installer will:

- install system dependencies, Docker, and Docker Compose if needed
- install Encodr into `/opt/encodr`
- generate local secrets and default config automatically
- start the stack
- verify health
- print the local URL, detected IP addresses, and next steps

You do not need to edit config files before first use.

## Manual install

If you prefer to inspect the files first:

1. clone the repository
2. run `sudo ./install.sh`
3. open the web UI and create the first admin user

See [docs/INSTALL.md](docs/INSTALL.md) for the full manual path.

If you specifically want a version-pinned install, use the same installer with an explicit version override:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | sudo bash -s -- --version 0.1.0
```

## First run

On first launch:

1. open the web UI
2. create the first admin user when prompted
3. confirm storage access on the System page
4. probe a file, plan it, create a job, and run the worker once

If your media storage is not mounted yet, Encodr will still start and let you sign in, but it will clearly warn that storage is not ready.

## Where the web UI will be

By default:

- UI: `http://<your-lxc-ip>:5173`
- API health: `http://<your-lxc-ip>:8000/api/health`

The installer prints the detected IP address and URLs when setup finishes.

## Storage and mounts

Encodr expects your media library at:

```text
/media
```

Recommended setup:

1. mount your NFS or SMB share on the Proxmox host
2. pass it into the LXC as a mount point
3. let Docker inside the LXC expose that same path to Encodr

Fallback Linux VM or bare Linux setup is also supported with a normal `/etc/fstab` mount at `/media`.

Use:

```bash
encodr mount-setup --validate-only
```

to confirm that Encodr can read and write the mounted path.

See [docs/STORAGE_SETUP.md](docs/STORAGE_SETUP.md) for the recommended mount models.

## Updating

The supported update command is:

```bash
encodr update
```

To apply an available update:

```bash
encodr update --apply
```

After an update, Encodr re-checks health automatically. The web UI can show when a newer release is available, but updates are still applied from the command line.

See [docs/UPDATES.md](docs/UPDATES.md).

## Basic usage flow

1. sign in
2. confirm storage health
3. probe a file by source path
4. review the plan and any warnings
5. create a job
6. run the worker
7. inspect verification, replacement, analytics, and manual review results in the UI

## Troubleshooting

Start with:

```bash
encodr doctor
encodr status
```

Then check:

- the System page in the web UI
- whether `/media` is mounted and writable
- whether `ffmpeg` and `ffprobe` are visible to the worker
- whether the first admin user has been created

Useful references:

- [docs/INSTALL.md](docs/INSTALL.md)
- [docs/STORAGE_SETUP.md](docs/STORAGE_SETUP.md)
- [docs/UPDATES.md](docs/UPDATES.md)
- [docs/SECURITY.md](docs/SECURITY.md)
- [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)
