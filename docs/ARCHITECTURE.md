# Architecture

## Repository shape

- `apps/api`: FastAPI control plane and authenticated API
- `apps/worker`: local execution worker
- `apps/ui`: React operator console
- `apps/worker-agent`: remote worker groundwork process
- `packages/core`: deterministic domain logic
- `packages/db`: persistence, migrations, repositories, and local runtime helpers
- `packages/shared`: small shared enums and types

## Runtime flow

1. A source path is probed with `ffprobe`.
2. Probe output is normalised into a stable `MediaFile`.
3. Policy and any matching profile override are resolved.
4. A deterministic `ProcessingPlan` is produced.
5. Probe and plan snapshots are persisted against a durable tracked-file record.
6. A job can be created from the plan.
7. The local worker executes the plan to scratch when appropriate.
8. Staged output is probed and verified against basic container, stream, and protection expectations.
9. Verified output is placed back into the source directory conservatively.
10. Manual-review or protected items require explicit operator action before processing continues.

## Service boundaries

- API owns auth, audit, operational endpoints, analytics endpoints, review actions, local worker run-once control, and worker registration/heartbeat control-plane endpoints.
- Worker owns local execution, verification, replacement, and local runtime status.
- UI owns the authenticated operator shell and typed API consumption.
- Worker-agent owns remote registration and heartbeat only.
- Core owns configuration, probe parsing, planning, execution mapping, verification rules, and replacement helpers.
- DB owns durable state and aggregate query helpers.

## Persistence model

- `tracked_files`: durable source identity and current operational state
- `probe_snapshots`: immutable normalised probe history
- `plan_snapshots`: immutable planning history
- `jobs`: execution, verification, replacement, and analytics outcomes
- `users`, `refresh_tokens`, `audit_events`: auth and security baseline
- `manual_review_decisions`: append-only review decision history
- `workers`: persisted remote worker identity, capability, auth-hash, and heartbeat state

## Local worker model

- local execution remains the only real execution path
- local worker status is projected into the same inventory shape as remote workers for the API and UI
- local worker health includes queue summary, binary discoverability, last run, and self-test results

## Remote worker groundwork

- remote workers register with a bootstrap secret
- the API issues a persistent worker token and stores only its hash
- remote workers heartbeat with explicit capability and health data
- remote workers are visible operationally and can be enabled/disabled
- remote workers do not poll, claim, or execute jobs yet

## Security model

- auth is mandatory for all non-health routes
- operational routes are currently admin-only
- bootstrap admin creation is first-run only
- worker auth is separate from user auth
- audit events cover user auth, review actions, and worker registration/state changes

## Testing model

- `unit`: deterministic logic and repository helpers
- `integration`: real FastAPI, migrations, DB, auth, and worker wiring
- `e2e`: controlled vertical slices across auth, DB, worker, verification, and UI-adjacent flows
- `smoke`: boot/runtime sanity
- `security`: auth, audit, and unsafe-regression coverage

## Future work

- remote job dispatch and execution
- richer scheduling and routing
- config editing UX
- deeper analytics and trend views
