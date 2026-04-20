# Encodr

Encodr is a private, self-hosted media ingestion preparation service for Plex-style libraries. It probes media with `ffprobe`, evaluates deterministic YAML policy, plans a conservative action, and then either skips, remuxes, transcodes, or routes the file into manual review before safe verified placement.

Encodr is intentionally narrow in scope. It is not a downloader, a Plex manager, or a broad workflow platform. The emphasis is on trust, reviewability, and safe handling of files on disk.

## Release status

- Current release line: `0.1.0`
- Maturity: internal `v0.x`
- Implemented: local auth, probe, planning, DB history, local worker execution, verification/replacement, operational API, UI shell, analytics, manual review/protected flows, and remote-worker registration/heartbeat groundwork
- Release hardening included: central versioning, update-check plumbing, root CLI management commands, fresh-LXC installer, first-user setup flow, and storage-mount validation guidance
- Not implemented: remote worker execution, advanced scheduling/orchestration, config editing UI, SSO, BI/report-builder features, automatic rollback for updates

## Current capabilities

- typed YAML configuration bootstrap with profile overlays and validation
- ffprobe ingestion into stable internal media models
- deterministic policy evaluation for `skip`, `remux`, `transcode`, and `manual_review`
- DB-backed tracked-file, probe, plan, job, review, audit, analytics, and worker state
- local worker execution with verification and safe replacement flow
- bootstrap-admin auth flow, JWT access tokens, refresh tokens, and audit logging
- authenticated operational API for files, jobs, review, analytics, config visibility, health, and workers
- authenticated UI for dashboard, files, jobs, manual review, reports, system health, config summary, and worker inventory
- remote worker registration and heartbeat groundwork with capability reporting

## Architecture overview

- `apps/api`: FastAPI control plane and authenticated operational API
- `apps/worker`: local execution worker for probe, plan, execute, verify, and replace
- `apps/ui`: React + Vite operator console
- `apps/worker-agent`: remote worker groundwork for register/heartbeat only
- `packages/core`: deterministic config, probe, planning, execution, verification, and replacement logic
- `packages/db`: SQLAlchemy models, Alembic migrations, repositories, and local worker runtime helpers
- `packages/shared`: small shared enums and types

## Prerequisites

- Python 3.11+ for local development in this repository
- Node.js 20+ and npm for the UI
- PostgreSQL 16+ for a closer-to-real local stack, though tests also use SQLite where appropriate
- Redis 7+ for the intended runtime stack
- `ffmpeg` and `ffprobe` available where the local worker runs

## First-run setup

1. Bootstrap local working files:

   ```bash
   make bootstrap
   ```

2. Review and update `.env`:
   - set `ENCODR_AUTH_SECRET`
   - set `ENCODR_WORKER_REGISTRATION_SECRET`
   - confirm `ENCODR_APP_CONFIG_FILE`, `ENCODR_POLICY_CONFIG_FILE`, and `ENCODR_WORKERS_CONFIG_FILE`

3. Review and adjust:
   - `config/app.yaml`
   - `config/policy.yaml`
   - `config/workers.yaml`

4. Start local dependencies if you want the Compose stack:

   ```bash
   make dev-up
   ```

5. If no users exist yet, either:
   - open the UI and follow the first-user setup form on the sign-in page, or
   - call `POST /api/auth/bootstrap-admin`, or
   - run `./encodr reset-admin --username admin`

## Fresh Debian LXC install

For a conservative fresh install inside a Debian LXC:

```bash
sudo ./install.sh
```

The installer:
- installs base packages plus Docker and Compose if missing
- bootstraps `.env` and `config/*.yaml`
- generates strong local secrets when placeholders are still present
- brings up the stack
- waits for API health
- prints detected IP addresses, URLs, and next steps

After install, use:

```bash
encodr doctor
encodr mount-setup --validate-only
encodr version
```

## Local development

Run the main processes in separate terminals:

```bash
make ui-install
make api
make worker
make ui
```

The API defaults to `http://localhost:8000/api` and the UI to `http://localhost:5173`.

## Operator CLI

The installed machine can use the root/operator CLI:

```bash
encodr version
encodr doctor
encodr update-check
encodr update
encodr reset-admin --username admin
encodr mount-setup --validate-only
```

`encodr update` uses release metadata plus a downloaded archive. It does not push git branches or merge to `main`.

## Auth bootstrap flow

Bootstrap admin creation is only available while no users exist.

Example:

```bash
curl -X POST http://localhost:8000/api/auth/bootstrap-admin \
  -H 'Content-Type: application/json' \
  -d '{
    "username": "admin",
    "password": "change-me-now"
  }'
```

Then sign in through the UI or the API:

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{
    "username": "admin",
    "password": "change-me-now"
  }'
```

## Operator flow

The current operator-ready path is:

1. log in
2. probe a file
3. plan a file
4. inspect reasons, warnings, and protected/manual-review state
5. create a job when safe
6. run the local worker once
7. inspect verification/replacement outcome
8. use Manual Review for ambiguous or protected items

Remote workers can register and heartbeat, but they do not execute jobs yet.

## Testing

Layered test commands:

```bash
make test-unit
make test-integration
make test-e2e
make test-security
make test-all
make check
```

Frontend-specific commands:

```bash
make ui-test
make ui-build
```

Release-maintainer helpers:

```bash
make version
make release-check
```

## Known limitations

- remote worker execution is not implemented
- advanced scheduling, balancing, and cluster orchestration are not implemented
- config editing through the UI is not implemented
- analytics are operational and useful, but not BI-grade
- naming policy exists, but advanced rich rename generation is still limited

See:
- [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)
- [CHANGELOG.md](CHANGELOG.md)

## Documentation map

- [docs/MEDIA_POLICY.md](docs/MEDIA_POLICY.md)
- [docs/SECURITY.md](docs/SECURITY.md)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/INSTALL.md](docs/INSTALL.md)
- [docs/STORAGE_SETUP.md](docs/STORAGE_SETUP.md)
- [docs/UPDATES.md](docs/UPDATES.md)
