# encodr

`encodr` is a private, self-hosted media ingestion preparation service for Plex-style libraries. It analyses media with `ffprobe`, evaluates deterministic YAML policy, and then decides whether to skip, remux, or transcode before files are ingested into the library.

The project is intentionally narrow in scope. It is not a downloader, a Plex manager, or a broad workflow automation platform. The goal is a reviewable and policy-driven preparation layer that favours trust, verification, and safe file handling.

## Current state

This repository currently contains:

- a working configuration bootstrap layer with validated YAML policy and profile loading
- ffprobe ingestion, normalised media models, and deterministic planning
- Postgres-oriented persistence with Alembic migrations and repository helpers
- a local worker flow for execute, verify, and safe replacement
- a local auth baseline with bootstrap admin creation, JWT access tokens, refresh tokens, and audit events
- layered tests covering unit, integration, end-to-end, smoke, and security cases

The broader job, file, and operational API surface is still intentionally narrow at this stage.

## Planned stack

- Python backend with FastAPI
- React + Vite frontend
- Postgres for persistent state
- Redis for queue and transient coordination
- `ffprobe` and `ffmpeg` integration
- policy-driven planning engine
- local worker first, with later remote worker support

## Quick start

1. Copy `.env.example` to `.env`.
2. Copy the example config files from `config/` to working versions if needed.
3. Review the documentation in `docs/`, starting with `PROJECT_OVERVIEW.md` and `MILESTONES.md`.
4. Bring up the scaffolded services with `docker compose up --build` once container details are filled in.

## Repository guide

- Project overview: [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Milestones: [docs/MILESTONES.md](docs/MILESTONES.md)
- Repo map: [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md)

## Testing

- `make test-unit`
- `make test-integration`
- `make test-e2e`
- `make test-security`
- `make test-all`
