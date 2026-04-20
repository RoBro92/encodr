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
