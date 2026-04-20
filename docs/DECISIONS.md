# Decisions

## Confirmed

- project name is `encodr`
- scope is ingestion preparation only
- backend is Python/FastAPI
- frontend is React/Vite
- Postgres is the target database
- Redis remains part of the target stack
- policy is YAML-driven and deterministic
- 4K defaults are preserve-video strip-only
- non-4K may be skip/remux/transcode
- auth is mandatory
- local worker is the only execution path for `0.1.x`
- manual review/protected flows are first-class and operator-driven
- analytics are operational, not BI-grade
- remote worker groundwork exists before remote execution
- local worker is projected into worker inventory rather than persisted as a worker row

## Groundwork decisions

- worker auth is separate from user auth
- remote workers register with a bootstrap secret and receive a token
- only the worker-token hash is stored
- remote workers heartbeat with explicit capability summaries rather than server-side guessing

## Deferred decisions

- final remote job dispatch protocol
- scheduling/routing strategy
- richer rename execution
- config editing UX
- long-term fingerprint/hash strategy
