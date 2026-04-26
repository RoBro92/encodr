# Security

Encodr can inspect and replace files on mounted media paths. Treat it as an internal, authenticated operations tool.

## Current Controls

- auth required for all non-health routes
- first-user bootstrap only when no users exist
- no open registration endpoint
- `argon2id` password hashing
- short-lived JWT access tokens
- opaque refresh tokens stored server-side as hashes
- admin-only operational API by default
- append-only audit logging for auth, review, and worker-security events
- sanitised effective-config visibility
- separate worker auth and user auth
- worker tokens stored server-side as hashes

## Secrets

Installed environments need strong values for:

- `POSTGRES_PASSWORD`
- `ENCODR_AUTH_SECRET`
- `ENCODR_WORKER_REGISTRATION_SECRET`

The installer generates these when placeholders are present. Do not commit `.env`, generated config, runtime state, worker token files, database volumes, or `dev-local/`.

## Network Exposure

Encodr is intended for a trusted internal network. If you expose it through a hostname:

- use a reverse proxy with TLS
- keep authentication enabled
- restrict access at the network boundary
- add the hostname with `encodr addhost <fqdn>`
- keep Postgres and Redis private

Do not expose worker registration to untrusted networks. Pair remote workers from trusted hosts only.

## Remote Workers

Remote workers can receive paths and execute work against shared storage. Only pair hosts you control. If you delete a remote worker in Encodr, run the shown uninstall command on the worker host to remove the local service and stored token.

Path mappings should point only at intended shared media roots. Avoid broad mappings such as filesystem roots.

## Updates

The UI may show update availability, but applying an update remains a host-side command-line action. Update checks depend on the configured release metadata source and should be treated as trusted release input.

## Out Of Scope

- SSO/OAuth/LDAP
- MFA
- API keys
- remote worker mTLS
- fine-grained RBAC beyond the current admin/operator baseline
