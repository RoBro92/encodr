# Milestones

Use this file as the delivery checklist and implementation ledger.

## Milestone 0: scaffold, docs, config examples, compose skeleton

- [x] PR 0.1 Create repository scaffold and starter files
- [x] PR 0.2 Write baseline architecture and policy documentation
- [x] PR 0.3 Add config examples, Compose skeleton, and starter entry points

## Milestone 1: config loading and validation

- [x] PR 1.1 Define typed app, policy, and worker config models
- [x] PR 1.2 Implement YAML loading, profile loading, and validation errors
- [x] PR 1.3 Add config-focused unit tests and sample fixtures

## Milestone 2: ffprobe metadata ingestion and internal models

- [x] PR 2.1 Define media, stream, and container models
- [x] PR 2.2 Implement ffprobe runner and JSON normalisation
- [x] PR 2.3 Add fixtures and tests for representative media cases

## Milestone 3: policy evaluation and planning engine

- [x] PR 3.1 Define plan model and decision explanation structure
- [x] PR 3.2 Implement language, subtitle, and audio retention logic
- [x] PR 3.3 Implement non-4K decision paths for skip, remux, and transcode
- [x] PR 3.4 Implement conservative 4K strip-only logic

## Milestone 4: DB schema and file/job state tracking

- [x] PR 4.1 Define initial tables for files, jobs, policy versions, and workers
- [x] PR 4.2 Add migration tooling and repository layer
- [x] PR 4.3 Persist processed-file state and idempotency checks

## Milestone 5: queue and local worker execution

- [x] PR 5.1 Define local job polling flow and execution lifecycle
- [x] PR 5.2 Implement local worker polling and job state updates
- [x] PR 5.3 Add execution wrappers for remux and transcode commands

## Milestone 6: verification and safe file replacement

- [x] PR 6.1 Implement output verification checks
- [x] PR 6.2 Implement scratch-to-destination replacement flow
- [x] PR 6.3 Add rollback and failure handling for unsafe replacements

## Milestone 7: auth and security baseline

- [x] PR 7.1 Add user model, password hashing, and login flow
- [x] PR 7.2 Add JWT/refresh-token auth handling
- [x] PR 7.3 Add audit logging for sensitive actions

## Milestone 7.5: testing and validation baseline

- [x] PR 7.5.1 Add layered pytest markers, shared helpers, and test DB bootstrapping
- [x] PR 7.5.2 Add integration coverage for auth, migrations, and worker execution flow
- [x] PR 7.5.3 Add end-to-end smoke coverage and selective test commands

## Milestone 8: operational API surface

- [x] PR 8.1 Add authenticated file and job read endpoints
- [x] PR 8.2 Add conservative probe, plan, job-create, retry, and worker run-once endpoints
- [x] PR 8.3 Add sanitised worker, system, and effective-config visibility endpoints

## Milestone 9: initial UI shell and dashboard

- [x] PR 9.1 Add UI shell, routing, and API client baseline
- [x] PR 9.2 Build dashboard views from live API data
- [x] PR 9.3 Add files, jobs, system, and config views

## Milestone 10: analytics and reporting

- [x] PR 10.1 Add aggregate analytics queries and reporting endpoints
- [x] PR 10.2 Expose operational outcome and storage metrics
- [x] PR 10.3 Add dashboard/reporting analytics UI

## Milestone 11: storage and worker health pages

- [x] PR 11.1 Enrich local worker status with queue and binary diagnostics
- [x] PR 11.2 Add storage and runtime health endpoints plus UI coverage
- [x] PR 11.3 Add worker self-test, degraded-state warnings, and health tests

## Milestone 12: manual review and protected-file flows

- [x] PR 12.1 Add protected-file rules and hold states
- [x] PR 12.2 Add manual approval/reject/hold actions
- [x] PR 12.3 Add review notes, audit traceability, and UI workflow

## Milestone 13: remote worker groundwork

- [x] PR 13.1 Define remote worker registration and auth contracts
- [x] PR 13.2 Implement worker-agent heartbeat and capability reporting
- [x] PR 13.3 Add worker inventory and future assignment groundwork

## Milestone 14: polish, docs refresh, and release prep

- [x] PR 14.1 Refresh docs to match implemented behaviour
- [x] PR 14.2 Tighten setup, validation, and local developer/operator ergonomics
- [x] PR 14.3 Add release-prep notes, known limitations, and final validation
