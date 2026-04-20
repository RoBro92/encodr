# Changelog

## Unreleased / Internal `0.1.7`

Initial internal release line covering:

- typed config/bootstrap and YAML policy validation
- ffprobe ingestion and deterministic planning
- tracked-file, snapshot, job, review, audit, analytics, and worker persistence
- local worker execution with verification and safe replacement
- authenticated API and operator UI
- analytics/reporting baseline
- manual review and protected-file workflows
- remote worker registration/heartbeat groundwork
- central versioning, update-check plumbing, and version visibility in API/UI/CLI
- root/operator CLI commands for doctor, update, reset-admin, and mount guidance
- fresh-LXC install/bootstrap script and first-user setup path
- dockerised doctor/runtime verification for installed and local Docker usage
- fresh-install cleanup now removes Encodr Docker containers, networks, local images, and volumes

Known important limitations:

- remote worker execution is not implemented
- advanced scheduling/orchestration is not implemented
- config editing remains read-only
- analytics are operational rather than BI-grade
