# Changelog

## 0.3.4 - 2026-04-22

This release focuses on worker orchestration, persistent scan state, watched jobs, schedule-aware dispatch, and conservative interruption handling.

- added explicit orchestration support for:
  - automatic worker distribution
  - preferred worker selection
  - pinned worker selection
  - preferred backend overrides
- added worker-level and job-level schedule windows so jobs can remain queued until an allowed execution window opens
- added persistent scan records for Library flows, including:
  - saved scan history
  - reopen previous scan results
  - rescan support
  - persisted scan summaries and discovered-file payloads
- added watched/default job definitions with:
  - source-path monitoring
  - optional ruleset override
  - optional preferred or pinned worker
  - optional preferred backend
  - optional schedule window
  - auto-queue or stage-only behaviour
- added conservative duplicate prevention for watched-folder ingestion so new files are not repeatedly queued
- added SSD-first source-path aware workflows by allowing watched jobs to target cache or download locations directly
- extended job state and API visibility with:
  - `scheduled`
  - `interrupted`
  - scheduled-for timestamps
  - schedule summaries
  - interruption reason and retryability
  - watched-job linkage
- added conservative worker interruption handling with a grace period and retry-from-start semantics rather than pretending cross-worker resume support
- improved Library, Jobs, and Workers UI flows just enough to support:
  - saved scans
  - watched jobs
  - schedule editing
  - worker and backend constraints
  - scheduled/interrupted job visibility
- preserved existing:
  - local and remote execution
  - per-worker backend preferences
  - progress reporting
  - dry-run and manual review safety
  - protected-file behaviour
- revalidated the platform with:
  - `pytest -q`
  - UI tests and production build

## 0.3.3 - 2026-04-22

This release focuses on platform completion for worker runtime selection, hardware-aware execution, managed container runtime configuration, and operational visibility.

- added backend-aware execution selection for:
  - CPU
  - Intel iGPU / QSV
  - NVIDIA GPU / NVENC
  - AMD GPU / AMF or VAAPI where truthfully available
- added requested vs actual backend tracking on jobs, including:
  - fallback-used reporting
  - backend selection reason
  - persisted backend metadata in the job model and API
- added app-managed runtime compose generation so Encodr can expose verified hardware paths to containers without manual docker-compose editing
- extended install and management CLI flows so runtime compose overrides are regenerated automatically during:
  - install
  - start / restart
  - rebuild
  - update
- improved worker assignment and local queue selection so jobs are matched conservatively against backend capability and CPU fallback policy
- extended local and remote worker runtime summaries with:
  - current job
  - current backend
  - current stage and progress
  - last progress timestamp
  - recent jobs
  - bounded live telemetry
- added truthful telemetry collection where the runtime can actually read it, including:
  - CPU usage
  - memory usage
  - process usage
  - CPU temperature where readable
  - NVIDIA and DRM/HWMON-backed GPU telemetry where readable
- completed the remote worker backend preference path so Windows worker bootstrap can carry:
  - preferred backend
  - CPU fallback policy
- improved Workers, Jobs, System, and Settings so they surface the new backend/runtime truth without broad UI redesign
- corrected Python packaging and installer repair behaviour so Debian 12 / Python 3.11 installs can repair and upgrade cleanly without manual path workarounds
- hardened the local validation harness for runtime-heavy scenarios by fixing local-only timing and terminal-state polling issues during stack bring-up and worker execution checks
- revalidated the full platform flow with:
  - `pytest -q`
  - UI tests and build
  - shell syntax checks
  - clean local scenario harness execution with local and remote worker success

## 0.3.2 - 2026-04-21

This release focuses on intelligent processing policy, progress visibility, and worker execution truth.

- expanded processing rules into four real persisted rulesets:
  - Movies
  - Movies 4K
  - TV
  - TV 4K
- added richer rules controls for:
  - preferred audio and subtitle languages
  - surround / 7.1 / Atmos preservation
  - handling mode
  - codec and container
  - video-only compression safety thresholds
- made compression safety depend on video reduction only, excluding savings from stripping audio and subtitles
- added real per-job ffmpeg progress capture and surfaced it through the Jobs API and UI
- added job progress and savings persistence fields plus the supporting database migration
- improved local and remote worker execution parity so both paths report video-only savings consistently
- hardened worker execution/runtime reporting and capability truth around progress, failure reporting, and hardware-path checks
- validated the worker and planning flows with a local-only scenario-driven media harness covering:
  - dry run
  - planning
  - local execution
  - remote execution
  - manual review
  - corruption and odd-metadata failure handling
  - compression-threshold safety behaviour

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
