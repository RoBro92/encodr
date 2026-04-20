# Security

## Baseline posture

`encodr` has access to networked media paths and can replace files. Authentication is therefore mandatory from the start of production use.

## Required controls

- Authentication required for all non-health endpoints
- Passwords stored as strong hashes, not reversible secrets
- `argon2id` password hashing for local credentials
- Short-lived JWT access tokens plus revocable refresh tokens
- Record audit logs for logins, configuration changes, job control actions, and manual review actions
- Follow least-privilege principles for containers, mounts, and worker file access

## Internal-network assumptions

- Initial deployment is on a trusted internal network, not the public internet
- Internal deployment reduces exposure but does not remove the need for authentication and auditability
- Reverse proxy, TLS, and network segmentation should still be considered part of production hardening

## Session approach

- API issues short-lived JWT access tokens for bearer authentication
- Refresh tokens are opaque, revocable, and stored server-side with rotation on refresh
- Logout revokes active refresh tokens for the current user
- `/health` remains public; operational and control endpoints require authenticated access

## Bootstrap admin

- First-run bootstrap admin creation is allowed only while no user records exist
- Once a user exists, bootstrap admin creation is blocked
- There is no open self-registration endpoint

## Audit trail

- Append-only audit events record bootstrap admin creation, bootstrap blocking, login success or failure, logout, and token refresh
- Events retain the acting username or user id where available, plus source IP, user agent, outcome, and structured details

## File-system and process controls

- mount only the required media paths
- separate scratch space from media libraries
- avoid running containers with broader permissions than needed
- prefer explicit worker capability registration over probing unsafe host details on demand

## Future work

- optional single-sign-on support
- mTLS for remote workers
- finer role-based access control
- signed job hand-off for remote execution
