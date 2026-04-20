# Architecture

## High-level shape

The repository is organised as a small monorepo:

- `apps/api`: FastAPI control plane and user-facing API
- `apps/worker`: local execution worker for probe, plan, execute, and verify flows
- `apps/ui`: React dashboard and operational UI
- `apps/worker-agent`: future remote worker process
- `packages/core`: deterministic domain logic
- `packages/db`: persistence models and repositories
- `packages/shared`: enums, types, and small shared contracts

## Runtime model

1. A file is discovered or submitted.
2. The worker probes it with `ffprobe`.
3. Core domain logic normalises probe output into stable internal media models.
4. The policy engine evaluates the file against YAML policy and selected profile overrides.
5. A deterministic plan is created: `skip`, `remux`, `transcode`, or `manual_review`.
6. The local worker polls pending jobs, converts the persisted plan into an execution command, and writes output to scratch space.
7. Staged outputs are probed and verified against the intended container, stream, and protection expectations before any final placement is attempted.
8. Verified outputs are placed back into the source directory with a conservative replacement flow that preserves the original on failure.
9. DB state records file identity, policy version, plan outcome, job lifecycle, staged output, verification result, and replacement outcome.

## Service boundaries

- API owns authentication, user/session handling, audit logging for security-relevant actions, job visibility, dashboard aggregation, configuration views, and administrative actions.
- Worker owns ffprobe, ffmpeg invocation, output verification, and safe replacement logic.
- Core package owns configuration loading, ffprobe parsing, internal media models, policy parsing, planning, naming, and verification rules.
- DB package owns persistent state and repository access patterns.
- Shared package stays intentionally small.

## Persistence layer

- `tracked_files` is the durable identity for a source path known to the system.
- Probe and plan snapshots are immutable historical records linked back to that tracked file.
- Jobs reference the chosen plan snapshot and carry execution, verification, and replacement state.
- Probe and plan snapshots remain immutable; job rows hold operational outcomes for later audit and analytics.
- Users, refresh tokens, and audit events provide the local authentication baseline for the API.

## Planning layer

- The planner consumes one normalised `MediaFile` plus the validated config bundle.
- Policy/profile resolution uses configured path-prefix overrides only.
- The planner returns a structured processing plan with action, selected stream intent, rename intent, replacement intent, reasons, warnings, and confidence.
- Stream selection intent is separated from execution details so later milestones can turn the plan into worker actions without changing the policy logic.

## Execution bridge

- The execution layer converts `ProcessingPlan` into a concrete local ffmpeg command plan.
- `skip` and `manual_review` jobs complete without invoking ffmpeg.
- `remux` uses explicit stream mapping with stream copy.
- `transcode` currently transcodes video to the target policy codec and preserves selected audio and subtitle streams by copy.
- ffmpeg success is only a staged outcome. Final completion now requires verification plus successful placement back into the source directory.

## Configuration bootstrap

- `packages/core` owns typed Pydantic models for app, policy, worker, and profile configuration.
- Bootstrap resolves `config/app.yaml`, `config/policy.yaml`, and `config/workers.yaml`, falling back to the corresponding `.example.yaml` file when the default file is absent.
- The three primary config file paths can be overridden with environment variables.
- Profile definitions are loaded from `config/profiles/` and referenced profile names are validated during bootstrap.

## Design constraints

- YAML policy is the source of truth for behaviour.
- 4K defaults are conservative: preserve video and strip only unwanted audio or subtitles.
- The planner must be deterministic and explain its decision.
- Output replacement must be safe and verifiable.
- Authentication is mandatory because the system has networked file access.
- Bootstrap access is tightly scoped to first-run admin creation only.

## Future expansion points

- remote worker registration and delegation
- richer manual review workflows
- UI-backed policy editing layered on top of YAML-backed config
- stronger storage awareness and scheduling decisions
