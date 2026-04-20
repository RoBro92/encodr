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

## Bootstrap admin

- first-run only
- blocked once any user exists
- no open registration endpoint

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

## Still out of scope

- SSO/OAuth/LDAP
- MFA
- API keys
- remote worker mTLS
- fine-grained RBAC beyond the current narrow admin/operator baseline
