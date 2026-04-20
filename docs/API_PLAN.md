# API Plan

## Purpose

The API is the control plane for authentication, queue visibility, operational state, manual review actions, configuration inspection, and analytics access.

## Early endpoint groups

- `GET /health`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`
- `GET /files`
- `GET /files/{file_id}`
- `GET /files/{file_id}/probe-snapshots/latest`
- `GET /files/{file_id}/plan-snapshots/latest`
- `POST /files/probe`
- `POST /files/plan`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs`
- `POST /jobs/{job_id}/retry`
- `GET /worker/status`
- `POST /worker/run-once`
- `GET /system/storage`
- `GET /system/runtime`
- `GET /config/effective`

## Current Milestone 8 scope

- All operational endpoints are authenticated and currently admin-only.
- Read endpoints expose tracked files, jobs, latest snapshots, worker status, storage status, runtime status, and sanitised effective config.
- Write endpoints are limited to probing, planning, job creation, retrying eligible jobs, and triggering one local worker pass.
- The API intentionally avoids broad CRUD or config mutation at this stage.

## API principles

- return explicit decision explanations, not opaque statuses
- avoid coupling list contracts directly to raw ffprobe JSON
- keep write operations auditable
- support pagination from the start where lists may grow
- do not expose secrets, password hashes, refresh token hashes, or raw auth material

## Milestone mapping

- Milestone 0: health endpoint only
- Milestone 7: auth baseline
- Milestone 8: operational endpoints
- Milestone 10 and 11: analytics and health pages
- Milestone 12: manual review actions
