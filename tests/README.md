# Tests

The test suite is layered so future milestones can add coverage without collapsing everything into slow end-to-end checks.

- `unit/`: deterministic checks for config loading, probe normalisation, planning, execution mapping, replacement, and auth helpers
- `integration/`: real FastAPI, SQLAlchemy, Alembic, auth, worker, and repository wiring with mocked ffmpeg or ffprobe only where external binaries would otherwise be required
- `e2e/`: controlled local-stack vertical slices that exercise API auth, persisted jobs, worker execution, verification, and file placement together
- `fixtures/`: representative ffprobe JSON payloads and related static inputs
- `helpers/`: reusable setup code for API clients, auth flows, DB bootstrapping, filesystem layout, and persisted job construction

Useful markers:

- `unit`
- `integration`
- `e2e`
- `smoke`
- `security`

Common commands:

- `make test-unit`
- `make test-integration`
- `make test-e2e`
- `make test-security`
- `make test-all`
