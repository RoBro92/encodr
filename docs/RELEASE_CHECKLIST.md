# Release Checklist

## Before using Encodr on a real media library

- [ ] review `docs/KNOWN_LIMITATIONS.md`
- [ ] set strong values for `ENCODR_AUTH_SECRET` and `ENCODR_WORKER_REGISTRATION_SECRET`
- [ ] copy example config to working files and review policy carefully
- [ ] verify scratch path and media mounts are correct
- [ ] run `encodr mount-setup --validate-only`
- [ ] verify ffmpeg/ffprobe paths
- [ ] run `encodr doctor`
- [ ] run `make check`
- [ ] bootstrap the first admin account
- [ ] test probe/plan/job/run-once on disposable media first
- [ ] confirm verification/replacement behaviour matches expectations
- [ ] review system, analytics, and worker inventory pages after first runs

## Recommended operational checks

- [ ] database backup approach in place
- [ ] NFS/media mount permissions verified
- [ ] local scratch free space monitored
- [ ] auth and worker registration secrets managed outside committed files
- [ ] remote worker registration restricted to trusted hosts only
- [ ] release metadata source for update checks reviewed and reachable
- [ ] `make release-check` run before tagging

## Live release publication

- [ ] update `VERSION`, `CHANGELOG.md`, and operator-facing docs
- [ ] run `make release-check`
- [ ] merge the approved release PR to `main`
- [ ] tag `main` with `v$(cat VERSION)`
- [ ] push `main` and the release tag
- [ ] confirm the GitHub Release workflow succeeds
- [ ] confirm the GitHub release is published and marked as a prerelease only for `-*` tags
- [ ] confirm GHCR packages exist for the release tag:
  - `ghcr.io/robro92/encodr-api`
  - `ghcr.io/robro92/encodr-ui`
  - `ghcr.io/robro92/encodr-worker`
  - `ghcr.io/robro92/encodr-worker-agent`
- [ ] run a fresh install or update check against the live tag before wider use
