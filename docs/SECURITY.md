# Security

## Baseline posture

Encodr can inspect and replace files on mounted media paths. Authentication and auditability are therefore mandatory.

## Current controls

- auth required for all non-health routes
- admin-only operational API by default
- `argon2id` password hashing
- short-lived JWT access tokens
- opaque revocable refresh tokens stored server-side
- append-only audit logging for auth, review, and worker-security events
- sanitised config visibility only
- bootstrap status endpoint only reports whether first-user setup is still required
- CLI admin reset is explicit, local to the installed host, and audited

## Bootstrap admin

- first-run only
- blocked once any user exists
- no open registration endpoint
- UI first-user setup uses the same bootstrap-admin backend path rather than a separate registration model

## Worker security baseline

- worker auth is separate from user auth
- bootstrap registration uses `ENCODR_WORKER_REGISTRATION_SECRET`
- remote workers receive a token on registration
- only the token hash is stored
- invalid worker auth and worker state changes are audited
- remote workers do not receive job execution authority yet

## Internal-network assumptions

- trusted internal network
- still requires auth, audit, and secret handling
- TLS/reverse proxy/network segmentation remain recommended for real deployment

## Operational notes

- `/config/effective` does not expose secrets
- worker inventory is admin-only
- manual-review/protected actions are explicit and audited
- local worker success requires verification and replacement success, not ffmpeg success alone
- `ENCODR_AUTH_SECRET` and `ENCODR_WORKER_REGISTRATION_SECRET` must be set outside committed config for real deployments
- update metadata may be checked from a configured source, but web-driven self-update remains read-only

## Still out of scope

- SSO/OAuth/LDAP
- MFA
- API keys
- remote worker mTLS
- fine-grained RBAC beyond the current narrow admin/operator baseline
