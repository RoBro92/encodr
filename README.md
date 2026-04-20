# encodr

`encodr` is a private, self-hosted media ingestion preparation service for Plex-style libraries. It analyses media with `ffprobe`, evaluates deterministic YAML policy, and then decides whether to skip, remux, or transcode before files are ingested into the library.

The project is intentionally narrow in scope. It is not a downloader, a Plex manager, or a broad workflow automation platform. The goal is a reviewable and policy-driven preparation layer that favours trust, verification, and safe file handling.

## Current state

This repository currently contains:

- a monorepo scaffold for the API, worker, UI, and shared packages
- starter documentation for architecture, policy behaviour, deployment, and milestones
- example YAML configuration files and policy profiles
- skeletal Docker Compose and Dockerfiles
- minimal runnable placeholders for the API, UI, and worker processes

No real media planning or execution logic has been implemented yet.

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

