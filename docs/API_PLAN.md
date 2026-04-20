# API Plan

## Purpose

The API is the authenticated operational control plane for Encodr.

## Implemented endpoint groups

- `GET /health`
- `POST /auth/bootstrap-admin`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/refresh`
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
- `GET /review/items`
- `GET /review/items/{item_id}`
- `POST /review/items/{item_id}/approve`
- `POST /review/items/{item_id}/reject`
- `POST /review/items/{item_id}/hold`
- `POST /review/items/{item_id}/mark-protected`
- `POST /review/items/{item_id}/clear-protected`
- `POST /review/items/{item_id}/replan`
- `POST /review/items/{item_id}/create-job`
- `GET /worker/status`
- `POST /worker/self-test`
- `POST /worker/run-once`
- `POST /worker/register`
- `POST /worker/heartbeat`
- `GET /workers`
- `GET /workers/{worker_id}`
- `POST /workers/{worker_id}/enable`
- `POST /workers/{worker_id}/disable`
- `GET /system/storage`
- `GET /system/runtime`
- `GET /config/effective`
- `GET /analytics/overview`
- `GET /analytics/storage`
- `GET /analytics/outcomes`
- `GET /analytics/media`
- `GET /analytics/recent`
- `GET /analytics/dashboard`

## Current API posture

- all operational endpoints are authenticated
- operational routes are currently admin-only
- health stays public
- config visibility is sanitised
- write operations are explicit and conservative
- worker registration/heartbeat is separate from user auth

## Groundwork only

- remote workers can register and heartbeat
- worker inventory can show local and remote workers together
- jobs can carry worker-association fields for future dispatch visibility

Remote workers cannot claim or execute jobs yet.

## Principles

- explicit, task-focused endpoints over broad CRUD
- typed responses
- auditable writes
- safe defaults
- no secret exposure
