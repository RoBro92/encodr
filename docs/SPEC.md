# Specification

## Problem

Media libraries often contain files that are technically usable but undesirable for long-term library ingestion because they contain the wrong languages, redundant tracks, poor codec choices, or ambiguous metadata. Encodr prepares those files with explicit policy and conservative execution.

## Implemented functional scope

- inspect media with `ffprobe`
- normalise probe metadata into typed internal models
- load and validate YAML app, policy, worker, and profile configuration
- resolve path-based profile overrides
- plan `skip`, `remux`, `transcode`, or `manual_review`
- persist tracked-file, probe, plan, job, review, audit, analytics, and worker state
- execute local remux/transcode jobs
- verify staged outputs before final placement
- replace or place files safely
- require authenticated operator access
- expose operational API/UI surfaces for files, jobs, review, analytics, health, config, and workers

## Important non-functional requirements

- deterministic planning
- explainable decisions
- append-only history where practical
- safe replacement and rollback posture
- clear operational visibility
- conservative security defaults

## Deferred scope

- remote worker execution
- advanced scheduling or balancing
- UI-driven config editing
- broad user management
- SSO, OAuth, LDAP, or public worker protocols
- BI/report-builder features

## Non-goals

- downloader automation
- Plex API/library administration
- general-purpose transcoding farm breadth
- replacing Tdarr/FileFlows in workflow scope
