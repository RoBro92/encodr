# Encodr

Encodr is a private, self-hosted media preparation service for Plex-style libraries. It inspects media before ingestion, applies conservative policy, and then safely skips, remuxes, transcodes, or sends a file to manual review before placing the verified result back into your library.

## Features

- probes media with `ffprobe` before any change is made
- uses deterministic policy rather than hidden automation
- treats 4K content conservatively by default
- keeps English audio and subtitles, including forced English subtitles
- preserves surround and Atmos-capable audio where possible
- verifies outputs before they are treated as successful
- provides a web UI for files, jobs, reports, manual review, and system health

## Install

Recommended install command:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash
```

The installer:

- installs dependencies
- creates local secrets automatically
- generates default config automatically
- starts the stack
- checks health
- prints the local URL and next steps
- installs the latest tagged release by default

You do not need to edit config files before first use.

## Manual Install

If you prefer to clone the repository first:

```bash
git clone https://github.com/RoBro92/encodr.git
cd encodr
./install.sh
```

If Encodr is already installed and you want to repair it in place:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --repair
```

If you need a destructive fresh reinstall:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --fresh --force-fresh
```

## Updates

Check for updates:

```bash
encodr update-check
```

Apply an update:

```bash
encodr update --apply
```

## Storage

Encodr uses `/media` as the standard media path.
Encodr uses `/temp` inside the stack as the standard transcode scratch path.

Recommended storage setup:

- Proxmox host mount -> LXC bind mount -> Docker `/media`
- LXC-local or host-mounted fast scratch disk -> LXC `/temp` -> Docker `/temp`
- or Linux VM mount via `/etc/fstab` to `/media`

The installer and bootstrap flow create `/media` and `/temp` automatically if they are missing. Encodr will still warn in the UI and system health views if those paths look empty or appear to share the container root filesystem instead of a real mount.

Encodr can start before storage is ready, but `/media` should be mounted and healthy before you run real jobs.

## First Run

On first run:

1. open the web UI
2. create the first admin user in the browser
3. confirm storage access on the System page

The first admin user is created through the web UI when no users exist yet.

## Basic Use

1. sign in
2. confirm health and storage access
3. probe a file by source path
4. review the plan and any warnings
5. create a job
6. run the worker
7. inspect the result in the UI

## Troubleshooting

Useful commands:

```bash
encodr doctor
encodr status
```

If something is wrong, check:

- whether the web UI is reachable
- whether `/media` is mounted and writable
- whether the System page reports storage or worker warnings
- whether the first admin user has been created

## More Help

- [Install guide](docs/INSTALL.md)
- [Storage setup](docs/STORAGE_SETUP.md)
- [Updates](docs/UPDATES.md)
- [Security notes](docs/SECURITY.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
