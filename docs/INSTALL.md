# Install

## Scope

This is the conservative install path for a fresh Debian LXC running the Encodr stack with Docker Compose inside the container.

## Recommended flow

1. Clone the repository into the LXC.
2. Run:

   ```bash
   sudo ./install.sh
   ```

3. Review the printed URLs and next steps.
4. Open the UI and complete first-user setup, or run:

   ```bash
   encodr reset-admin --username admin
   ```

## What `install.sh` does

- installs base OS packages
- installs Docker Engine and the Compose plugin if missing
- bootstraps `.env` and `config/*.yaml`
- generates local secrets if placeholders are still present
- creates runtime directories
- starts the Compose stack
- waits for API health
- runs `encodr doctor`
- prints local IP addresses and suggested next steps

## After install

- review `config/app.yaml`, `config/policy.yaml`, and `config/workers.yaml`
- run `encodr mount-setup --validate-only`
- verify scratch and media paths before touching a real library
- use the UI or API bootstrap flow only while no users exist

## Out of scope

- Proxmox host reconfiguration from inside the LXC
- automatic TLS or reverse-proxy setup
- remote worker execution
