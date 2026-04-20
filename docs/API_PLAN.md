# API Plan

## Purpose

The API is the control plane for authentication, queue visibility, operational state, manual review actions, configuration inspection, and analytics access.

## Early endpoint groups

- `GET /health`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/retry`
- `GET /files`
- `GET /files/{file_id}`
- `GET /workers`
- `GET /storage`
- `GET /analytics/summary`
- `GET /policy/current`

## API principles

- return explicit decision explanations, not opaque statuses
- avoid coupling API contracts directly to raw ffprobe JSON
- keep write operations auditable
- support pagination from the start where lists may grow

## Milestone mapping

- Milestone 0: health endpoint only
- Milestone 7: auth baseline
- Milestone 8: operational endpoints
- Milestone 10 and 11: analytics and health pages
- Milestone 12: manual review actions

