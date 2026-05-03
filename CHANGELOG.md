# Changelog

## 0.4.3 - 2026-05-03

This hotfix improves replacement retry handling for installs where verified output could not be moved into place.

- allowed retrying replacement-failure manual-review jobs when the file itself does not require protected or planner review
- kept protected replacement failures behind the existing manual-review gate
- made verified output placement tolerate cross-device moves by falling back to content copy without metadata preservation
- retained move-strategy details in replacement results for diagnosis
- revalidated with:
  - `pytest tests/unit/test_verification_replacement.py tests/integration/test_api_operations_integration.py -q`
  - `bash infra/scripts/release-check.sh`

## 0.4.2 - 2026-05-01

This hotfix restores updates for installs that moved to the 0.4.1 hardening release and then found the API container would not become healthy.

- fixed API startup when preserved diagnostic log directories from older installs are not writable by the new non-root API user
- repaired updater startup handling so preserved `/data` and scratch bind mounts are made writable for the non-root API and worker containers before Docker Compose starts them
- trimmed update/install sync output so repo-only files such as docs, tests, CI workflow files, and root developer metadata are not copied into `/opt/encodr`
- kept the non-root container hardening from 0.4.1 in place
- revalidated with:
  - `pytest -q`
  - `cd apps/ui && npm test -- --run`
  - `cd apps/ui && npm run build`
  - `python3 -m compileall apps packages tests encodr_cli.py`
  - `bash -n install.sh`
  - `bash -n encodr`
  - `bash -n infra/scripts/*.sh`

## 0.4.1 - 2026-05-01

This release hardens Encodr for pre-production installs after the 0.4.0 release, with safer worker result handling, more reliable queue behavior, and clearer runtime reporting.

- tightened remote worker result path validation so worker-reported files are mapped back to trusted server paths before Encodr stores, deletes, restores, or cleans them up
- hardened API and worker container defaults by running services with non-root users and stricter runtime privileges
- improved startup and shutdown handling so background orchestration is owned by the API lifecycle and test runs do not leave worker threads behind
- made several concurrent operations more deterministic, including refresh-token rotation, first-admin bootstrap, worker job claims, bulk queue startup, and backup restore conflicts
- improved backup and setup-state handling so restore conflicts are checked before file mutation and corrupt setup state is surfaced more clearly
- aligned backend/runtime metadata shared by API, worker, and UI so worker diagnostics show more consistent binary and backend information
- improved UI/API type coverage for worker runtime fields without changing the operator workflow
- revalidated with:
  - `pytest -q`
  - `cd apps/ui && npm test -- --run`
  - `cd apps/ui && npm run build`
  - `python3 -m compileall apps packages tests encodr_cli.py`
  - `bash -n install.sh`
  - `bash -n encodr`
  - `bash -n infra/scripts/*.sh`
  - GitHub CI for backend, UI, and sanity checks

## 0.4.0 - 2026-04-30

This release improves day-to-day operation around queues, backups, reviews, dashboard navigation, and worker diagnostics.

- added clearer Dashboard entry points into the matching Jobs and Review views
- improved Jobs filtering and tab navigation so active, completed, failed, cancelled, skipped, and review work are easier to browse
- added backup search, pagination, visible selection, bulk delete controls, and more accurate backup totals when files have already been removed
- improved Review filtering and item navigation so decisions stay focused on the selected queue
- made Review failures easier to handle by keeping the current item visible if a list refresh fails
- improved skipped-job presentation so policy skips are not shown as failures
- improved worker diagnostics and backend display so operators can better understand current worker state
- revalidated with:
  - `pytest -q`
  - `cd apps/ui && npm test -- --run`
  - `cd apps/ui && npm run build`
  - `python3 -m compileall apps packages tests encodr_cli.py`
  - GitHub CI for backend, UI, and sanity checks

## 0.3.8.1 - 2026-04-29

This hotfix restores the update path for installs moving onto the 0.3.8 release line.

- fixed an update-time configuration error that could stop `encodr update --apply` while checking bundled profile files
- kept bundled movie and TV profiles compatible with older updater checks
- changed future updates so the post-update health check runs through the newly installed CLI instead of the older updater process
- revalidated with:
  - `pytest -q`
  - `bash -n install.sh`
  - `bash -n encodr`

## 0.3.8 - 2026-04-29

This release hardens Encodr for pre-production use, with safer job handling, clearer worker setup, better quality decisions, and more dependable release packaging.

- added quality-aware processing controls so Encodr can make clearer keep, review, or transcode decisions based on configured expectations
- added dashboard and queue filtering improvements so operators can find active, completed, failed, cancelled, and review work more quickly
- improved worker health reporting so local and remote worker readiness is easier to understand before jobs are assigned
- made cancellation safer so cancelled work does not falsely report that media was untouched when replacement has already completed
- prevented duplicate active jobs for the same tracked file while still allowing new work after previous jobs finish
- tightened worker assignment so jobs are claimed by one eligible worker at a time
- improved remote worker onboarding so default installs no longer start an automatic remote worker, and remote workers must be added intentionally
- improved remote worker credential handling so pairing details are not kept around longer than needed after setup
- made default Docker Compose startup safer by keeping database and Redis ports internal unless a local override is used
- improved verification for non-English audio and subtitle preferences so selected language intent is checked more accurately
- fixed profile path matching so similarly named folders do not accidentally receive the wrong processing profile
- improved sign-in/session behavior, including clearer wrong-password messages instead of object-shaped error text
- reduced unnecessary background refresh work for live job progress while keeping the UI responsive
- strengthened release validation so images are not published unless the release checks pass first
- updated deployment, worker, and security documentation to match the safer default startup and remote worker setup flow
- revalidated with:
  - `pytest -q`
  - `cd apps/ui && npm test -- --run`
  - `cd apps/ui && npm run build`
  - `python3 -m compileall apps packages tests encodr_cli.py`
  - `bash -n install.sh`
  - `bash -n encodr`
  - `bash -n infra/scripts/*.sh`
  - GitHub CI for backend, UI, and sanity checks

## 0.3.7.1 - 2026-04-27

This release candidate tightens queue control, processed-file safety, backup handling, diagnostics logging, and Settings diagnostics presentation before public release.

- removed the normal-user Batch Plan action from the Library UI while retaining backend planning for job creation, dry runs, watched jobs, and review flows
- added active queue controls, failed/cancelled clearing, explicit cancelled job status handling, and safer local cancellation cleanup for staged outputs
- separated active, completed, and failed/cancelled jobs in the Jobs UI and replaced anonymous status pills with labelled, explainable badges
- fixed processed-file state so files are only marked processed after completed verification, successful replacement, final output presence, and backup handling
- added per-job backup policy persistence, backup delete/restore API/UI, and automatic cleanup for expired one-day retained backups
- added structured diagnostics logging, 7-day log retention, Settings log viewing, and downloadable diagnostic bundles with optional path redaction
- moved Settings diagnostics into a compact header action and viewport-locked modal with a scrollable log console
- revalidated with:
  - `pytest -q`
  - `cd apps/ui && npm test -- --run`
  - `cd apps/ui && npm run build`
  - `python3 -m compileall apps packages tests encodr_cli.py`
  - `bash -n install.sh`
  - `bash -n encodr`
  - `bash -n infra/scripts/*.sh`

## 0.3.7 - 2026-04-27

This patch release fixes stale Intel VAAPI capability reporting after worker image updates.

- refreshed local worker capability data from the actual worker runtime on startup and heartbeat instead of relying on API-container probes
- ignored stale local capability payloads unless they are fresh worker-runtime reports
- added `which vainfo` diagnostics, including command, return code, stdout, and stderr, to Intel VAAPI failure payloads
- expanded remote worker-agent heartbeat capability payloads with `vainfo` binary diagnostics and hardware probe details
- added regression coverage for stale `vainfo missing` data being replaced when the current worker runtime reports `/usr/bin/vainfo`
- revalidated with:
  - `pytest -q`
  - `cd apps/ui && npm test -- --run`
  - `cd apps/ui && npm run build`
  - `python3 -m compileall apps packages tests encodr_cli.py`

## 0.3.6 - 2026-04-26

This release prepares Encodr for a cleaner public repository and tightens first-install security defaults without changing UI behaviour, worker execution, processing rules, or API contracts.

- simplified public documentation around:
  - install and update flow
  - deployment and storage expectations
  - local and remote workers
  - processing rules and dry-run safety
  - security posture and known limitations
- reduced the public docs set to the user-facing README, changelog, and focused docs under `docs/`
- moved developer-only planning, release-process, UI handoff, and local demo notes into the ignored `dev-local/` workspace for local reference
- added a local-only milestone/roadmap summary covering completed capabilities, outstanding validation, backlog ideas, and release caveats
- removed private/internal doc ignore exceptions so future local planning material stays under `dev-local/`
- replaced the public example Postgres password with an explicit placeholder
- updated the installer so fresh installs generate `POSTGRES_PASSWORD` and sync the generated value into the app database DSN
- replaced a private-looking test hostname with a reserved example hostname
- fixed local checkout install sync so deleted tracked paths in cleanup branches do not break external install-root sync
- revalidated with:
  - `pytest -q`
  - `cd apps/ui && npm test -- --run`
  - `cd apps/ui && npm run build`
  - `python3 -m compileall apps packages tests encodr_cli.py`
  - `bash -n install.sh`
  - `bash -n encodr`
  - `bash -n infra/scripts/*.sh`

## 0.3.5 - 2026-04-25

This live release completes the 0.3.5 release-candidate line with a broad UI polish pass and scale-focused queue/dashboard architecture work.

- refined the operator UI into a more cohesive SaaS-style surface, including:
  - cleaner warning/action banners without nested white boxes
  - standardized form control and button heights
  - path truncation with hover titles on Jobs and Review
  - stronger Dashboard outcome coloring and active-transcode progress presentation
  - centered Library empty states
  - consolidated Jobs queue controls
  - badge-based Jobs metadata
  - boxed and aligned Jobs/Review top metrics
  - a minimal login page with accessible placeholder-only fields
- added live job progress streaming through Server-Sent Events so Dashboard and Jobs progress can update without REST polling
- added persisted telemetry aggregation storage and a rebuild fallback so Dashboard summary stats avoid full-table scans as job history grows
- added exponential retry backoff for transient job failures before routing work to manual Review
- kept worker execution, dry-run, watched-folder, scheduling, and review flows compatible with the 0.3.5 release-candidate line
- updated release documentation and the release workflow so stable tags publish GHCR images for:
  - `ghcr.io/robro92/encodr-api`
  - `ghcr.io/robro92/encodr-ui`
  - `ghcr.io/robro92/encodr-worker`
  - `ghcr.io/robro92/encodr-worker-agent`
- revalidated locally with:
  - `pytest`
  - `npm run test -- App.test.tsx`
  - `npm run build`
  - Docker stack health checks

## 0.3.5-rc.2 - 2026-04-23

This release candidate focuses on UI/functionality stabilisation ahead of the next design pass, with an emphasis on operator clarity, truthful worker diagnostics, safer queue handling, and library scalability.

- reworked the Workers page so inventory stays compact and worker detail no longer stretches the page layout
- refocused worker detail around operator value, surfacing:
  - health summary
  - degraded reasons
  - preferred vs usable backends
  - current activity
  - queue/concurrency summary
  - storage/path access
  - telemetry and recent jobs
- improved local worker diagnostics so Intel iGPU/runtime issues are shown clearly, including:
  - `/dev/dri` visibility
  - ffmpeg and ffprobe readiness
  - configured backend health
  - CPU fallback-in-effect visibility
  - clearer degraded-state explanations
- added job cancellation support for:
  - queued jobs
  - scheduled jobs
  - safe local running jobs
  while keeping unsafe remote and running dry-run cancellation paths conservative
- clarified queue and progress presentation with:
  - real vertical worker accordions
  - clearer per-job stage labels
  - better handling of 0%-but-active jobs
  - clearer cancelled vs interrupted visibility
  - visually distinct dry-run jobs
- corrected queue artwork sourcing so random frame extraction is no longer used as the default visual
- scaled Library workspace behaviour with:
  - search
  - pagination
  - TV show/season/episode hierarchy
  - bulk selection for shows, seasons, and visible result sets
- preserved existing:
  - worker onboarding and editing
  - per-worker backend, path-mapping, and scratch configuration
  - scheduling and watched jobs
  - dry-run jobs
  - rules and compression safety
  - local and remote execution
- revalidated the branch with:
  - `pytest -q`
  - UI tests and production build
  - clean local harness execution with `15/15` scenarios passing
  - local and remote execution validated
  - dry-run job validation

## 0.3.5-rc.1 - 2026-04-23

This release candidate focuses on worker inventory correction, per-worker storage/runtime configuration, worker-backed dry runs, and grouped operational visibility.

- corrected the worker model so no workers appear by default and only explicitly configured local workers or paired remote workers appear in inventory
- moved worker execution/runtime configuration fully to the worker level, including:
  - preferred backend
  - CPU fallback policy
  - concurrency
  - schedule windows
  - per-worker scratch paths
  - per-worker path mappings
- simplified Settings to the intended sections:
  - Library folders
  - Storage
  - Updates
  - Processing rules
- reworked Workers around explicit onboarding and modal configuration flows, including:
  - Add worker
  - Add this host as worker
  - Add remote worker
  - modal-based worker editing
  - remote uninstall/revoke guidance
- hardened remote worker bootstrap and runtime handling with:
  - sane OS-specific install locations
  - pairing/runtime configuration carrying scratch and mapping data
  - safer remote preview handling for transport payloads
  - hardened pairing/runtime serialisation for mapped workers
- implemented direct shared-storage remote execution support through:
  - server-path to worker-path mappings
  - worker-local scratch paths
  - mapping-aware assignment and execution assumptions
- turned dry run into a real background worker job with:
  - worker assignment
  - schedule-aware launch handling
  - queue visibility
  - persisted analysis payloads
  - file-count warning prompts
  - richer per-file analysis output
- extended Jobs to keep worker-grouped queue views while adding:
  - richer queue item presentation
  - worker summaries
  - dry-run visibility
  - local-first artwork support via sidecars or frame extraction
- revalidated the branch with:
  - `pytest -q`
  - UI tests and production build
  - clean local harness execution with `15/15` scenarios passing
  - local and remote execution validated
  - dry-run background job validation
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
