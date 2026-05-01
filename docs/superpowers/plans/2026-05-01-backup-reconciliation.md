# Backup Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make historic `.encodr-backup` files visible in the backup log during library scans and safely restorable into manual review.

**Architecture:** Extend library scanning to detect backup artifacts separately from processable media. Persist discovered backups as synthetic completed job records linked to minimal tracked/probe/plan snapshots, so existing backup listing, search, delete, and restore endpoints continue to work.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, existing Encodr DB repositories and API schemas.

---

### Task 1: Scan Detects and Persists Historic Backups

**Files:**
- Modify: `apps/api/app/services/library.py`
- Modify: `apps/api/app/services/orchestration.py`
- Modify: `apps/api/app/schemas/files.py`
- Modify: `packages/db/encodr_db/repositories/jobs.py`
- Test: `tests/integration/test_api_operations_integration.py`
- Test: `tests/unit/test_db_repositories.py`

- [ ] **Step 1: Write failing integration test**

Add a test that creates `Example Film.mkv` and `Example Film.encodr-backup.mkv`, calls `POST /api/files/scan`, asserts `video_file_count == 1`, `backup_file_count == 1`, then calls `GET /api/jobs/backups?search=Example` and asserts the discovered backup appears.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/integration/test_api_operations_integration.py::test_scan_reconciles_historic_backup_files_into_backup_log -q`
Expected: failure because `backup_file_count` is absent and backups are not persisted from scan.

- [ ] **Step 3: Implement minimal scan and persistence**

Add backup detection to `LibraryService.scan_directory`; add `backup_file_count` and `backup_files` to scan payloads and schemas. Add repository method `reconcile_discovered_backup(...)` that creates a tracked file for the inferred original path and a completed synthetic job with `original_backup_path`, `final_output_path`, `backup_policy="discovered"`, `replacement_status=SUCCEEDED`, and `verification_status=NOT_REQUIRED` if no active backup job already points at the backup path.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/integration/test_api_operations_integration.py::test_scan_reconciles_historic_backup_files_into_backup_log -q`
Expected: pass.

### Task 2: Restore Leaves Manual Review History

**Files:**
- Modify: `apps/api/app/services/jobs.py`
- Modify: `apps/api/app/api/jobs.py`
- Test: `tests/integration/test_api_operations_integration.py`

- [ ] **Step 1: Write failing restore test**

Add a test that scans a discovered backup, restores it through `POST /api/jobs/{job_id}/backup/restore`, asserts the transcoded/current file is gone, the backup is renamed to the original path, the tracked file is in manual review, and a manual review decision note contains `Restored from backup`.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/integration/test_api_operations_integration.py::test_restore_discovered_backup_returns_file_to_manual_review_with_note -q`
Expected: failure because restore currently does not create a manual review history note.

- [ ] **Step 3: Implement restore history**

Pass the authenticated user into `JobsService.restore_backup`. After moving the backup back, create a `ManualReviewDecision` with type `HELD`, note `Restored from backup; review whether to skip or reprocess.`, and details containing backup path and restored source path.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/integration/test_api_operations_integration.py::test_restore_discovered_backup_returns_file_to_manual_review_with_note -q`
Expected: pass.

### Task 3: Regression Sweep

**Files:**
- Existing touched files and backup-related tests.

- [ ] **Step 1: Run focused backup and scan tests**

Run: `pytest tests/integration/test_api_operations_integration.py::test_scan_excludes_encodr_backup_and_temp_artifacts tests/integration/test_api_operations_integration.py::test_scan_reconciles_historic_backup_files_into_backup_log tests/integration/test_api_operations_integration.py::test_restore_discovered_backup_returns_file_to_manual_review_with_note tests/unit/test_db_repositories.py::test_backup_listing_supports_search_pagination_and_total_after_missing_files_are_filtered tests/unit/test_db_repositories.py::test_expired_backup_cleanup_deletes_retained_backup -q`
Expected: pass.

- [ ] **Step 2: Run static/API import checks if needed**

Run: `pytest tests/unit/test_api_jobs_static.py -q`
Expected: pass.
