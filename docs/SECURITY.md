# Security

## Baseline posture

`encodr` has access to networked media paths and can replace files. Authentication is therefore mandatory from the start of production use.

## Required controls

- Authentication required for all non-health endpoints
- Passwords stored as strong hashes, not reversible secrets
- Prefer `argon2id` for password hashing
- Use short-lived access tokens plus refresh tokens or equivalent server-side session control
- Record audit logs for logins, configuration changes, job control actions, and manual review actions
- Follow least-privilege principles for containers, mounts, and worker file access

## Internal-network assumptions

- Initial deployment is on a trusted internal network, not the public internet
- Internal deployment reduces exposure but does not remove the need for authentication and auditability
- Reverse proxy, TLS, and network segmentation should still be considered part of production hardening

## Session approach

- API issues short-lived JWT access tokens
- Refresh tokens are revocable and stored server-side or in a revocation-aware model
- UI stores tokens using the least risky approach chosen during implementation

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

