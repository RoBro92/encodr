# Project Overview

## Purpose

Encodr prepares media files for ingestion into Plex-style libraries. It probes source files, applies deterministic YAML policy, and then either skips, remuxes, transcodes, or routes the file into manual review before safe verified placement.

## Product stance

- internal tool first
- conservative and auditable by default
- deterministic planning over hidden heuristics
- safe replacement over aggressive automation
- narrow scope rather than broad workflow automation

## Implemented now

- typed config bootstrap with profile validation
- ffprobe ingestion and normalised media models
- deterministic planning with structured reasons and warnings
- local worker execution with verification and safe replacement
- tracked-file, probe, plan, job, audit, analytics, review, and worker persistence
- authenticated operational API and UI
- manual review and protected-file workflows
- remote worker registration and heartbeat groundwork

## Groundwork only

- remote worker identity, capability reporting, enablement, and heartbeat
- worker-agent CLI for register/heartbeat only
- job-to-worker association fields for future dispatch visibility

## Explicitly not included yet

- remote worker job execution
- advanced scheduling, balancing, or autoscaling
- public worker protocol
- broad config editing UI
- downloader or Plex management features
- BI-style analytics or report builder features

## Deployment assumptions

- Debian LXC host
- Docker Compose inside the LXC
- NFS-mounted media paths
- local NVMe scratch
- main worker local first

## Readiness posture

Encodr is at an internal `v0.x` stage. It is usable for conservative operator-driven flows, but it should still be treated as a controlled internal tool rather than a fully hardened general release.
