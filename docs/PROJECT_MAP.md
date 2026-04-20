# Project Map

## Root

- `README.md`: current product overview, setup, auth bootstrap, testing, and limitations
- `.env.example`: local environment baseline
- `docker-compose.yml`: local stack for API/UI/worker/dependencies
- `Makefile`: common local run, bootstrap, test, and check targets
- `CHANGELOG.md`: internal release notes draft

## `docs/`

- `PROJECT_OVERVIEW.md`: product scope and current implementation line
- `ARCHITECTURE.md`: runtime, persistence, and service boundaries
- `SPEC.md`: implemented and deferred requirements
- `MEDIA_POLICY.md`: current planning/policy behaviour
- `MILESTONES.md`: completed milestone ledger
- `PROJECT_MAP.md`: this file
- `API_PLAN.md`: implemented API surface and principles
- `DATA_MODEL.md`: durable and in-memory model summary
- `SECURITY.md`: current auth, audit, and worker-auth baseline
- `DEPLOYMENT.md`: deployment assumptions and operator notes
- `UI_PLAN.md`: current UI information architecture
- `ANALYTICS_PLAN.md`: current operational analytics shape
- `WORKER_PLAN.md`: local worker and remote-worker groundwork
- `RENAMING_RULES.md`: current naming direction and limits
- `DECISIONS.md`: confirmed architectural decisions
- `RELEASE_CHECKLIST.md`: internal release-readiness checklist
- `KNOWN_LIMITATIONS.md`: explicit current limitations

## `config/`

- `app.example.yaml`: app/runtime defaults
- `policy.example.yaml`: baseline media policy
- `workers.example.yaml`: local worker plus remote-worker groundwork examples
- `profiles/`: reusable policy profile examples

## `apps/`

- `api/`: FastAPI app, auth, files/jobs/review/analytics/system/worker routes, schemas, and services
- `worker/`: local execution worker entry point and orchestration shell
- `ui/`: authenticated React operator console
- `worker-agent/`: remote worker groundwork for registration, heartbeat, capability reporting, and token handling

## `packages/`

- `core/encodr_core/config/`: typed config models, bootstrap, and validation
- `core/encodr_core/probe/`: ffprobe execution and parsing
- `core/encodr_core/media/`: stable media/domain models
- `core/encodr_core/planning/`: deterministic plan generation and reasons
- `core/encodr_core/execution/`: plan-to-ffmpeg mapping and runner support
- `core/encodr_core/verification/`: staged-output verification rules
- `core/encodr_core/replacement/`: safe placement/replacement helpers
- `db/encodr_db/models/`: SQLAlchemy models for files, snapshots, jobs, users, audit, review, and workers
- `db/encodr_db/repositories/`: persistence and aggregate query helpers
- `db/encodr_db/runtime/`: local worker run-once/runtime helpers
- `db/encodr_db/migrations/`: Alembic environment and revisions
- `shared/`: small shared enums and type helpers

## `infra/`

- `docker/`: Dockerfiles for API, worker, UI, and worker-agent
- `scripts/bootstrap.sh`: create local working config/env files if missing
- `scripts/dev-up.sh`: start the Compose stack with a minimal guard
- `scripts/lint.sh`: lightweight compile sanity check

## `tests/`

- `unit/`: deterministic logic and repository tests
- `integration/`: real app/DB/auth/runtime integration
- `e2e/`: controlled vertical-slice flows
- `fixtures/`: representative ffprobe/static fixtures
- `helpers/`: reusable test setup helpers

## Current release note

The repository now reflects a usable internal `0.1.0` baseline. Remote worker execution and advanced orchestration remain intentionally out of scope.
