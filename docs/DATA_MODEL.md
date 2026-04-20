# Data Model

## Durable entities

- `tracked_files`: durable source identity and current operational state
- `probe_snapshots`: immutable normalised probe history
- `plan_snapshots`: immutable processing-plan history
- `jobs`: execution, verification, replacement, and analytics outcomes
- `users`: local authenticated operators
- `refresh_tokens`: revocable refresh-token state
- `audit_events`: append-only audit log
- `manual_review_decisions`: append-only review/protection decisions
- `workers`: persisted remote worker identity, capability, and heartbeat state

## Tracked-file fields of note

- source path, filename, extension, and directory
- last observed size and modified time
- `is_4k`
- lifecycle/compliance state
- protected/review fields
- last processed policy version

## Snapshot model

- probe and plan snapshots are immutable
- latest snapshot access is derived, not by mutating old records
- jobs reference one chosen plan snapshot
- review decisions reference the relevant file/plan/job context without rewriting history

## Job model

Jobs persist:

- status and attempts
- staged output path
- verification status/payload
- replacement status/payload
- final output path and backup path
- failure message/category
- measured input/output sizes
- worker association groundwork fields

## Worker model

Remote workers persist:

- stable worker key and display name
- worker type and enablement
- token hash
- capability, host, runtime, and binary summaries
- registration and heartbeat timestamps
- health summary/status

The local worker is projected into the same API shape, but is not persisted as a row.

## In-memory models

- `MediaFile` and typed stream/container models from probing
- `ProcessingPlan` and related plan-intent models from planning

These remain the source for deterministic planning and execution mapping.
