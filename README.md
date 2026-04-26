# Encodr

Encodr is a self-hosted media preparation service for Plex-style libraries. It probes media, applies explicit processing rules, and then skips, remuxes, transcodes, dry-runs, or sends files to manual review before verified output is placed back into the library.

Encodr is designed for cautious, operator-driven use. It favours explainable decisions, staged output, verification, and manual review over hidden automation.

## Features

- `ffprobe`-based media inspection before processing
- Movies, Movies 4K, TV, and TV 4K processing rules
- conservative 4K handling by default
- audio/subtitle language selection with surround and Atmos-aware preservation
- dry-run analysis for files, folders, and watched jobs
- local and remote worker execution
- per-worker backend preferences, schedules, concurrency, scratch paths, and path mappings
- verified output staging before replacement
- manual review and protected-file flows
- authenticated web UI for library scans, jobs, workers, review, reports, settings, and system health

## Install

For a Debian LXC or Linux VM:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash
```

The installer installs Docker if needed, creates local config, generates local secrets, starts the stack, runs health checks, and prints the local UI URL.

To install from a clone:

```bash
git clone https://github.com/RoBro92/encodr.git
cd encodr
./install.sh
```

See [docs/INSTALL.md](docs/INSTALL.md) for version pinning, repair, fresh reinstall, and update commands.

## Quick Start

1. Open the web UI printed by the installer.
2. Create the first admin user.
3. Confirm storage health on the System page.
4. Add this host as a local worker, or pair a remote worker from Workers.
5. Scan or browse a library path.
6. Run a dry run on representative files.
7. Queue real work only after the plan and warnings look right.

Useful host commands:

```bash
encodr status
encodr doctor
encodr mount-setup --validate-only
```

## Storage

Encodr expects:

- `/media` for the media library inside the stack
- `/temp` for transcode scratch space inside the stack

For Proxmox LXC deployments, mount NFS/SMB storage on the Proxmox host, bind it into the LXC, and let Docker expose the same path to Encodr. Keep scratch storage on fast local or NVMe-backed storage where possible.

Remote workers must be able to read and write the same media through shared storage. If a worker sees the share at a different path, configure worker path mappings in the Workers page.

## Workers

The local worker runs in the Encodr stack and is disabled until you add it from the Workers page. Remote workers pair back to Encodr as background agents on Windows, Linux, or macOS. Each worker has its own backend preference, CPU fallback setting, schedule windows, concurrency, scratch path, and storage mappings.

See [docs/WORKERS.md](docs/WORKERS.md) before enabling real processing.

## Processing Rules

Processing rules decide whether files are skipped, remuxed, transcoded, or sent to manual review. Defaults are conservative, especially for 4K, HDR/Dolby Vision-like, and Atmos-capable media. Use dry runs before processing a real library.

See [docs/MEDIA_POLICY.md](docs/MEDIA_POLICY.md) for the current rules and safety model.

## Updates

Check for an update:

```bash
encodr update-check
```

Apply an update:

```bash
encodr update --apply
```

The web UI can show update notices, but applying updates remains a host-side operator action.

## More Docs

- [Install](docs/INSTALL.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Workers](docs/WORKERS.md)
- [Media policy](docs/MEDIA_POLICY.md)
- [Security](docs/SECURITY.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
