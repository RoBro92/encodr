# Data Model

## Core persistent entities

- `tracked_files`: durable source-file identity, last-seen metadata, lifecycle state, compliance state, and last processed policy metadata
- `probe_snapshots`: immutable normalised probe payload snapshots linked to a tracked file
- `plan_snapshots`: immutable persisted processing plans linked to both tracked file and probe snapshot
- `jobs`: queue-oriented job records linked to the tracked file and selected plan snapshot, including staged output, verification, and replacement outcomes

## Core in-memory media model

- `MediaFile`: one normalised representation of a probed file
- `ContainerFormat`: file-level container metadata such as format, duration, bitrate, and size
- `VideoStream`, `AudioStream`, `SubtitleStream`: typed stream models with normalised tags and disposition
- `AttachmentStream`, `DataStream`, `UnknownStream`: lighter stream models for non-primary stream types
- `Chapter`: normalised chapter boundaries and titles

These models are produced directly from ffprobe JSON in Milestone 2 so Milestone 3 can consume a stable domain object rather than raw ffprobe output.

## Core in-memory planning model

- `ProcessingPlan`: one deterministic planning result for a file
- `PolicyContext`: selected policy version and matched profile override context
- `AudioSelectionIntent`, `SubtitleSelectionIntent`, `VideoPlan`, `ContainerPlan`: execution-facing intent without command generation
- `PlanReason` and `PlanWarning`: stable explanation objects for operator review and later API/UI surfacing

## Important relationships

- A tracked file can have many probe snapshots.
- A tracked file can have many plan snapshots.
- Each plan snapshot references one probe snapshot and one policy version.
- A tracked file can have many jobs over time.
- A job references one plan snapshot, though retries are still represented as separate job rows.

## Execution-state persistence

- job rows persist the staged output path produced by ffmpeg
- verification status and verification payload are stored on the job
- replacement status, final output path, backup path, and replacement failure details are stored on the job
- tracked files only move to fully completed and compliant after verification and final placement succeed

## Key modelling concerns

- distinguish source file identity from current path
- keep probe and planning history immutable for later audit and analytics use
- make idempotency possible so already-processed files under the same policy can be detected safely
- keep plan explanations queryable for debugging and review

## Milestone timing

- domain models begin in Milestone 2
- DB schema lands in Milestone 4
- verification and safe replacement state lands in Milestone 6
- analytics rollups likely land in Milestone 10
