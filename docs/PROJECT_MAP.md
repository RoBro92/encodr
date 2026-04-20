# Project Map

## Root

- `README.md`: top-level project description and quick start
- `.env.example`: baseline environment variables
- `docker-compose.yml`: local development stack skeleton
- `Makefile`: convenience targets for placeholder services

## `docs/`

- `PROJECT_OVERVIEW.md`: product purpose and scope boundaries
- `ARCHITECTURE.md`: runtime and repository architecture
- `SPEC.md`: baseline requirements and non-goals
- `MEDIA_POLICY.md`: intended policy behaviour
- `MILESTONES.md`: milestone and PR checklist
- `PROJECT_MAP.md`: this file
- `API_PLAN.md`: planned API surface
- `DATA_MODEL.md`: planned persistent and domain data model
- `SECURITY.md`: security baseline
- `DEPLOYMENT.md`: deployment assumptions
- `UI_PLAN.md`: UI shape and information architecture
- `ANALYTICS_PLAN.md`: planned metrics and reporting
- `WORKER_PLAN.md`: worker execution model
- `RENAMING_RULES.md`: Plex-friendly naming rules
- `DECISIONS.md`: architectural and product decisions already made

## `config/`

- `app.example.yaml`: general app settings
- `policy.example.yaml`: default policy and path overrides
- `workers.example.yaml`: local worker plus future remote worker examples
- `profiles/`: reusable example policy profile overlays

## `apps/`

- `api/`: FastAPI service entry point, auth routes, dependencies, schemas, and service-layer wiring
- `worker/`: local worker entry point and execution module placeholders
- `ui/`: Vite + React starter UI
- `worker-agent/`: future remote worker control-plane process

## `packages/`

- `core/`: shared deterministic business logic
- `core/encodr_core/config/`: typed config models, YAML loading, bootstrap resolution, and validation shaping
- `core/encodr_core/media/`: normalised media/container/stream models and probe normalisation helpers
- `core/encodr_core/planning/`: deterministic policy evaluation, profile resolution, stream selection intent, and plan models
- `core/encodr_core/probe/`: ffprobe client, parser, and structured probe errors
- `db/`: persistence layer and migrations
- `db/encodr_db/models/`: SQLAlchemy models for tracked files, snapshots, jobs, users, refresh tokens, and audit events
- `db/encodr_db/repositories/`: repository helpers for file, snapshot, job, auth, and audit persistence
- `db/encodr_db/migrations/`: Alembic environment and revision history
- `shared/`: small enums and type helpers

## `infra/`

- `docker/`: skeletal container definitions
- `scripts/`: project utility scripts

## `tests/`

- `fixtures/`: sample metadata and future anonymised media fixtures
- `unit/`: deterministic unit tests
- `integration/`: service and persistence integration tests
- `e2e/`: full workflow and UI tests

## Current naming note

The repository now uses `encodr_*` package names consistently across code, packaging metadata, and documentation.
