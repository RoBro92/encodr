# Install

## Recommended one-command install

For a Debian LXC or Linux VM, run:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | sudo bash
```

The installer will:

- install required system packages, Docker, and the Docker Compose plugin if missing
- install Encodr into `/opt/encodr`
- create `.env` and default config automatically
- generate local secrets if they are still placeholders
- start the stack
- verify health with `encodr doctor`
- print the local URL, detected IP addresses, and next steps

No manual config editing is required before first use.

To install a specific release instead:

```bash
curl -fsSL https://raw.githubusercontent.com/RoBro92/encodr/main/install.sh | sudo bash -s -- --version 0.1.0
```

## Manual install

If you want to inspect the checkout first:

```bash
git clone https://github.com/RoBro92/encodr.git
cd encodr
sudo ./install.sh
```

## After install

1. open the web UI
2. create the first admin user if prompted
3. confirm storage access on the System page
4. run `encodr mount-setup --validate-only`
5. run `encodr doctor` or `encodr status`
6. probe and plan a test file before touching a real library

## Re-running the installer

Running `install.sh` again is safe for repair-style use. It reuses the existing install tree, refreshes bootstrap files if they are missing, starts the stack, and re-checks health.

For normal upgrades after install, prefer:

```bash
encodr update
encodr update --apply
```
