# Changelog

## Unreleased / Internal `0.3.0`

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
- `/temp` mount support for transcode scratch storage
- storage health now warns when `/media` or `/temp` do not look like real mounted storage
- folder-first library browsing and mounted root-path selection for Movies and TV
- dry-run planning for single files, selected files, and whole folders
- folder scan summaries and batch planning/job creation for library paths
- cleaner setup, dashboard, and navigation copy for day-to-day operator use
- phased UI redesign across Dashboard, Library, Jobs, Review, System, and Settings
- real editable Movies and TV processing rules in Settings, backed by persisted runtime state
- improved tracked-file selection for job creation and cleaner folder-first library workflow
- clearer Reports access from the dashboard without restoring primary-nav clutter
- configurable UI host allowlisting for operator FQDNs
- `encodr addhost <fqdn>` host-side helper to update `.env` and recreate the stack
- dedicated UI asset folders for future icons and images
- truthful local worker capability reporting for ffmpeg, ffprobe, scratch/media readiness, and hardware acceleration probes
- remote worker assignment, polling, claiming, execution, and result submission
- Windows-first remote worker bootstrap documentation and install script
- local-only ffmpeg-generated E2E media harness for real stack validation
- verified local and remote worker E2E execution flow against controlled media samples

Known important limitations:

- advanced scheduling/orchestration is not implemented
- remote worker progress reporting remains intentionally simple
- Windows is the first documented remote worker target; broader Linux/macOS packaging is still follow-on work
- config editing remains intentionally narrow rather than a full generic editor
- analytics are operational rather than BI-grade
