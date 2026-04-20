# Project Overview

## Purpose

`encodr` prepares media files for ingestion into Plex-style libraries. It inspects files with `ffprobe`, evaluates deterministic YAML policy, and decides whether each file should be skipped, remuxed, or transcoded before safe replacement or return to the original folder.

The product is intentionally limited to ingestion preparation. It does not handle downloading, Plex library management, or broad workflow automation.

## Product stance

- Internal tool first, but structured so it can be opened later
- Policy-driven behaviour, not hidden heuristics
- Reviewability over breadth
- Safe file handling over aggressive automation
- Deterministic planning so the same input and policy produce the same decision

## First deployment target

- Debian LXC host
- Docker Compose running inside the LXC
- Postgres and Redis in the same Compose stack
- media on NFS share
- local NVMe scratch for transient work files
- Intel iGPU acceleration if available on the main worker

## Core capabilities in scope

- media scanning and metadata inspection
- policy evaluation from YAML
- separate handling for non-4K and 4K content
- DB-backed processed-file state and policy version tracking
- queue-driven worker execution
- API and UI for dashboard, jobs, workers, storage, and analytics
- authentication and auditability

## Out of scope for now

- download clients or indexers
- Plex API management
- general-purpose workflow automation
- automatic metadata fetching beyond what is required for local naming
- multi-tenant features

## Immediate milestone target

Milestone 0 establishes the scaffold only. Real media logic starts in Milestone 1.

