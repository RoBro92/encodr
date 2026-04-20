# Install

## Recommended one-command install

For a Debian LXC or Linux VM, run:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash
```

The installer will:

- install required system packages, Docker, and the Docker Compose plugin if missing
- install Encodr into `/opt/encodr`
- create `.env` and default config automatically
- generate local secrets if they are still placeholders
- start the stack
- verify health with `encodr doctor`
- print the local URL, detected IP addresses, and next steps
- install the latest tagged release by default

No manual config editing is required before first use.

To install a specific release instead:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --version <tag>
```

## Manual install

If you want to inspect the checkout first:

```bash
git clone https://github.com/RoBro92/encodr.git
cd encodr
./install.sh
```

## After install

1. open the web UI
2. create the first admin user if prompted
3. confirm storage access on the System page
4. run `encodr mount-setup --validate-only`
5. run `encodr doctor` or `encodr status`
6. probe and plan a test file before touching a real library

## Re-running the installer

If an existing install is found, the installer will stop and ask what to do. It will not repair automatically.

For a non-interactive repair run:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --repair
```

For a destructive fresh reinstall:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | bash -s -- --fresh --force-fresh
```

Fresh reinstall removes the Encodr install tree, generated config, runtime state, and local database volumes before reinstalling.

For normal upgrades after install, prefer:

```bash
encodr update
encodr update --apply
```
