# Install

## One-Command Install

Run the installer as root on a Debian LXC or Linux VM:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash
```

The remote installer installs the latest tagged release by default.

The installer will:

- install required system packages, Docker, and the Docker Compose plugin if missing
- install Encodr into `/opt/encodr`
- create `.env` and default config from examples
- generate local auth, worker-registration, and database secrets when placeholders are present
- create `/media` and `/temp` if they do not already exist
- generate runtime Docker Compose overrides for detected hardware
- start the stack
- run `encodr doctor`
- print the local UI URL and next steps

No config editing is required before the first start.

To install a specific release:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --version <tag>
```

## Manual Checkout

To inspect the release first:

```bash
git clone https://github.com/RoBro92/encodr.git
cd encodr
./install.sh
```

## First Run

1. Open the web UI.
2. Create the first admin user.
3. Confirm `/media` and `/temp` on the System page.
4. Run `encodr mount-setup --validate-only`.
5. Run `encodr doctor` or `encodr status`.
6. Add a local or remote worker from Workers.
7. Run a dry run against disposable or representative media before queueing real work.

## Storage

Encodr uses `/media` as the standard in-stack media root and `/temp` as the standard scratch workspace. The installer creates both paths if missing, but real processing should wait until `/media` is mounted and writable and `/temp` points at suitable scratch storage.

Validation:

```bash
encodr mount-setup --validate-only
```

Host-side guidance examples:

```bash
encodr mount-setup --type nfs --host-source nfs-server.example:/share
encodr mount-setup --type smb --host-source //fileserver.example/share
```

## Repair Or Reinstall

If an existing install is found, the installer stops and asks what to do.

Repair in place:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --repair
```

Destructive fresh reinstall:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --fresh --force-fresh
```

Fresh reinstall removes the install tree, generated config, runtime state, and local database volumes before reinstalling.

## Updates

Check for updates:

```bash
encodr update-check
```

Apply an update:

```bash
encodr update --apply
```

Updates preserve local runtime files such as `.env`, `.runtime`, config, and live database volumes, then rebuild/restart the Docker stack and run health checks. Automatic rollback is not implemented, so run `encodr doctor` after updates if you want an extra manual check.

## Links

- [Deployment](./DEPLOYMENT.md)
- [Workers](./WORKERS.md)
- [Security](./SECURITY.md)
- [Known limitations](./KNOWN_LIMITATIONS.md)
