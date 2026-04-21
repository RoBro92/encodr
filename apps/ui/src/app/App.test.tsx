import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { makeSession, mockFetchRoutes, renderApp, resetBrowserState } from "../test/test-utils";

const CURRENT_VERSION = __ENCODR_VERSION__;

function nextPatchVersion(version: string): string {
  const parts = version.split(".");
  const patch = Number.parseInt(parts.at(-1) ?? "0", 10);
  if (Number.isNaN(patch)) {
    return `${version}-next`;
  }
  return [...parts.slice(0, -1), String(patch + 1)].join(".");
}

describe("Encodr UI shell", () => {
  beforeEach(() => {
    resetBrowserState();
  });

  afterEach(() => {
    resetBrowserState();
  });

  it("shows the login screen when an unauthenticated user opens a protected route", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/auth/bootstrap-status",
        body: {
          bootstrap_allowed: false,
          first_user_setup_required: false,
          user_count: 1,
          version: CURRENT_VERSION,
        },
      },
    ]);

    renderApp({ route: "/" });

    expect(await screen.findByRole("heading", { name: /sign in to the operator console/i })).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`encodr v${CURRENT_VERSION}`, "i"))).toBeInTheDocument();
  });

  it("shows the first-user setup flow when bootstrap is still allowed", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/auth/bootstrap-status",
        body: {
          bootstrap_allowed: true,
          first_user_setup_required: true,
          user_count: 0,
          version: CURRENT_VERSION,
        },
      },
      {
        method: "POST",
        path: "/api/auth/bootstrap-admin",
        body: {
          user: {
            id: "user-1",
            username: "admin",
            role: "admin",
            is_active: true,
            is_bootstrap_admin: true,
            last_login_at: null,
          },
        },
      },
      {
        method: "POST",
        path: "/api/auth/login",
        body: {
          access_token: "new-access",
          refresh_token: "new-refresh",
          token_type: "bearer",
          access_token_expires_in: 1800,
          refresh_token_expires_in: 1209600,
        },
      },
      {
        method: "GET",
        path: "/api/auth/me",
        body: {
          id: "user-1",
          username: "admin",
          role: "admin",
          is_active: true,
          is_bootstrap_admin: true,
          last_login_at: null,
        },
      },
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/login" });

    expect(await screen.findByRole("heading", { name: /set up the first admin user/i })).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/username/i));
    await userEvent.type(screen.getByLabelText(/username/i), "admin");
    await userEvent.type(screen.getByLabelText(/^password$/i), "super-secure-password");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "super-secure-password");
    await userEvent.click(screen.getByRole("button", { name: /create first admin/i }));

    expect(await screen.findByRole("heading", { name: /^dashboard$/i })).toBeInTheDocument();
  });

  it("shows a bootstrap-status error instead of falling back silently to sign in", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/auth/bootstrap-status",
        status: 500,
        body: { detail: "bootstrap status unavailable" },
      },
    ]);

    renderApp({ route: "/login" });

    expect(await screen.findByRole("heading", { name: /unable to load sign-in state/i })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/bootstrap status unavailable/i);
  });

  it("renders the simplified dashboard navigation and entry points", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^dashboard$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^library$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^manual review$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^workers$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^system$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^config$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open library/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^reports$/i, hidden: false })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/probe source path/i)).not.toBeInTheDocument();
  });

  it("shows an update banner when a newer version is available", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      {
        method: "GET",
        path: "/api/system/update",
        body: {
          current_version: CURRENT_VERSION,
          latest_version: nextPatchVersion(CURRENT_VERSION),
          update_available: true,
          channel: "internal",
          status: "ok",
          release_name: `Encodr v${nextPatchVersion(CURRENT_VERSION)}`,
          release_summary: "Installer fixes and update improvements.",
          checked_at: "2026-04-20T12:30:00Z",
          error: null,
          download_url: "https://example.invalid/encodr.tar.gz",
          release_notes_url: "https://example.invalid/encodr-notes",
        },
      },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: new RegExp(`encodr ${nextPatchVersion(CURRENT_VERSION)} is ready to install`, "i") })).toBeInTheDocument();
    expect(screen.getByText(/installer fixes and update improvements/i)).toBeInTheDocument();
    expect(screen.getAllByText(/encodr update --apply/i)[0]).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(`update ${nextPatchVersion(CURRENT_VERSION)} available`, "i") })).toBeInTheDocument();
  });

  it("lets an operator skip the current update while keeping a subtle indicator", async () => {
    const latestVersion = nextPatchVersion(CURRENT_VERSION);
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      {
        method: "GET",
        path: "/api/system/update",
        body: {
          current_version: CURRENT_VERSION,
          latest_version: latestVersion,
          update_available: true,
          channel: "internal",
          status: "ok",
          release_name: `Encodr v${latestVersion}`,
          release_summary: "Installer fixes and update improvements.",
          checked_at: "2026-04-20T12:30:00Z",
          error: null,
          download_url: "https://example.invalid/encodr.tar.gz",
          release_notes_url: "https://example.invalid/encodr-notes",
        },
      },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    await userEvent.click(await screen.findByRole("button", { name: /skip update/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(window.localStorage.getItem("encodr:update:skip-version")).toBe(latestVersion);
    expect(screen.getByRole("button", { name: new RegExp(`update ${latestVersion} available`, "i") })).toBeInTheDocument();
  });

  it("lets an operator choose Movies and TV folders from the config page", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: null,
          tv_root: "/media/TV",
        },
      },
      {
        method: "GET",
        path: "/api/files/browse",
        body: {
          root_path: "/media",
          current_path: "/media",
          parent_path: null,
          entries: [
            { name: "Movies", path: "/media/Movies", entry_type: "directory", is_video: false },
            { name: "TV", path: "/media/TV", entry_type: "directory", is_video: false },
          ],
        },
      },
      {
        method: "PUT",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
    ]);

    renderApp({ route: "/config", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^setup$/i })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /choose folder/i })[0]);

    const dialog = await screen.findByRole("dialog", { name: /choose movies folder/i });
    expect(within(dialog).getByText("/media")).toBeInTheDocument();
    await userEvent.click(within(dialog).getAllByRole("button", { name: /^choose$/i })[0]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/config/setup/library-roots"),
        expect.objectContaining({ method: "PUT", headers: expect.any(Headers) }),
      );
    });
  });

  it("scans a folder and runs a dry run from the library page", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
      {
        method: "POST",
        path: "/api/files/scan",
        body: {
          folder_path: "/media/Movies",
          root_path: "/media",
          directory_count: 2,
          direct_directory_count: 2,
          video_file_count: 2,
          likely_show_count: 0,
          likely_season_count: 0,
          likely_episode_count: 0,
          likely_film_count: 2,
          files: [
            { name: "Film One (2024).mkv", path: "/media/Movies/Film One (2024).mkv", entry_type: "file", is_video: true },
            { name: "Film Two (2024).mkv", path: "/media/Movies/Film Two (2024).mkv", entry_type: "file", is_video: true },
          ],
        },
      },
      {
        method: "POST",
        path: "/api/files/dry-run",
        body: {
          mode: "dry_run",
          scope: "selection",
          total_files: 1,
          protected_count: 0,
          review_count: 0,
          actions: [{ value: "transcode", count: 1 }],
          items: [
            {
              source_path: "/media/Movies/Film One (2024).mkv",
              file_name: "Film One (2024).mkv",
              action: "transcode",
              confidence: "high",
              requires_review: false,
              is_protected: false,
              reason_codes: ["video_transcode_required_for_policy_codec"],
              warning_codes: [],
              selected_audio_stream_indices: [1],
              selected_subtitle_stream_indices: [],
            },
          ],
        },
      },
    ]);

    renderApp({ route: "/files", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^library$/i })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /^scan$/i })[0]);

    expect(await screen.findByText(/likely films/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /film one/i }));
    await userEvent.click(screen.getByRole("button", { name: /dry run selected/i }));

    const dryRunHeading = await screen.findByRole("heading", { name: /dry run/i });
    const dryRunCard = dryRunHeading.closest(".section-card") as HTMLElement | null;
    expect(dryRunCard).not.toBeNull();
    expect(screen.getByText(/read-only preview of what encodr would do/i)).toBeInTheDocument();
    if (dryRunCard) {
      expect(within(dryRunCard).getByText(/film one \(2024\)\.mkv/i, { selector: "strong" })).toBeInTheDocument();
    }
  });

  it("creates batch jobs from a scanned folder", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
      {
        method: "POST",
        path: "/api/files/scan",
        body: {
          folder_path: "/media/Movies",
          root_path: "/media",
          directory_count: 2,
          direct_directory_count: 2,
          video_file_count: 2,
          likely_show_count: 0,
          likely_season_count: 0,
          likely_episode_count: 0,
          likely_film_count: 2,
          files: [
            { name: "Film One (2024).mkv", path: "/media/Movies/Film One (2024).mkv", entry_type: "file", is_video: true },
            { name: "Film Two (2024).mkv", path: "/media/Movies/Film Two (2024).mkv", entry_type: "file", is_video: true },
          ],
        },
      },
      {
        method: "POST",
        path: "/api/jobs/batch",
        body: {
          scope: "folder",
          total_files: 2,
          created_count: 1,
          blocked_count: 1,
          items: [
            {
              source_path: "/media/Movies/Film One (2024).mkv",
              status: "created",
              message: null,
              job: {
                ...jobDetail(),
                id: "job-1",
                tracked_file_id: "file-1",
              },
            },
            {
              source_path: "/media/Movies/Film Two (2024).mkv",
              status: "blocked",
              message: "This file requires manual review or protected-file approval before a job can be created.",
              job: null,
            },
          ],
        },
      },
    ]);

    renderApp({ route: "/files", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^library$/i })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /^scan$/i })[0]);
    await userEvent.click(await screen.findByRole("button", { name: /create jobs for folder/i }));

    const batchJobsSection = await screen.findByRole("heading", { name: /batch jobs/i });
    const batchJobsCard = batchJobsSection.closest(".section-card") as HTMLElement | null;
    expect(batchJobsCard).not.toBeNull();
    if (batchJobsCard) {
      expect(within(batchJobsCard).getByRole("link", { name: /open job/i })).toBeInTheDocument();
      expect(within(batchJobsCard).getByText(/^Created$/i, { selector: ".metric-label" })).toBeInTheDocument();
      expect(within(batchJobsCard).getByText(/^Blocked$/i, { selector: ".metric-label" })).toBeInTheDocument();
      expect(within(batchJobsCard).getByText(/manual review or protected-file approval/i)).toBeInTheDocument();
    }
  });
});

function analyticsDashboard() {
  return {
    overview: {
      total_tracked_files: 12,
      protected_file_count: 2,
      four_k_file_count: 3,
      jobs_by_status: [
        { value: "pending", count: 1 },
        { value: "completed", count: 5 },
        { value: "failed", count: 2 },
      ],
      plans_by_action: [
        { value: "skip", count: 2 },
        { value: "remux", count: 4 },
        { value: "transcode", count: 3 },
      ],
    },
    storage: {
      total_space_saved_bytes: 1073741824,
      average_space_saved_bytes: 536870912,
      savings_by_action: [
        { action: "remux", space_saved_bytes: 268435456, job_count: 1 },
        { action: "transcode", space_saved_bytes: 805306368, job_count: 1 },
      ],
    },
    outcomes: {
      jobs_by_status: [
        { value: "completed", count: 5 },
        { value: "failed", count: 2 },
      ],
      verification_by_status: [],
      replacement_by_status: [],
      top_failure_categories: [],
      container_distribution: [],
    },
    media: {
      latest_probe_english_audio_count: 5,
      latest_probe_forced_subtitle_count: 2,
      latest_probe_surround_audio_count: 3,
      latest_probe_atmos_audio_count: 1,
    },
    recent: {
      recent_completed_jobs: [
        {
          job_id: "job-1",
          file_name: "Example Film (2024).mkv",
          action: "remux",
          status: "completed",
          updated_at: "2026-04-20T11:15:00Z",
        },
      ],
      recent_failed_jobs: [
        {
          job_id: "job-2",
          file_name: "Broken Film (2024).mkv",
          action: "transcode",
          status: "failed",
          updated_at: "2026-04-20T12:15:00Z",
        },
      ],
    },
  };
}

function workerStatus() {
  return {
    status: "healthy",
    summary: "The local worker is healthy and available.",
    worker_name: "worker-local",
    mode: "single-node-local",
    local_only: true,
    enabled: true,
    available: true,
    default_queue: "local-default",
    ffmpeg: binaryStatus(),
    ffprobe: binaryStatus(),
    local_worker_queue: "local-default",
    last_run_started_at: "2026-04-20T10:04:30Z",
    last_run_completed_at: "2026-04-20T10:05:00Z",
    last_processed_job_id: "job-1",
    last_result_status: "completed",
    last_failure_message: null,
    processed_jobs: 4,
    capabilities: { ffmpeg: true, ffprobe: true, intel_qsv: false },
    queue_health: queueHealth(),
    self_test_available: true,
  };
}

function binaryStatus() {
  return {
    configured_path: "/usr/bin/ffmpeg",
    discoverable: true,
    exists: true,
    executable: true,
    status: "healthy",
    message: "Binary is discoverable and executable.",
  };
}

function queueHealth() {
  return {
    status: "healthy",
    summary: "Queue health is within expected bounds.",
    pending_count: 1,
    running_count: 0,
    failed_count: 1,
    manual_review_count: 1,
    completed_count: 4,
    oldest_pending_age_seconds: 3600,
    last_completed_age_seconds: 300,
    recent_failed_count: 1,
    recent_manual_review_count: 1,
  };
}

function runtimeStatus() {
  return {
    status: "healthy",
    summary: "Runtime health is healthy.",
    version: CURRENT_VERSION,
    environment: "production",
    db_reachable: true,
    schema_reachable: true,
    auth_enabled: true,
    api_base_path: "/api",
    standard_media_root: "/media",
    scratch_dir: "/temp",
    data_dir: "/data",
    media_mounts: ["/media"],
    local_worker_enabled: true,
    first_user_setup_required: false,
    storage_setup_incomplete: false,
    user_count: 1,
    config_sources: {
      app: "/opt/encodr/config/app.yaml",
      policy: "/opt/encodr/config/policy.yaml",
      workers: "/opt/encodr/config/workers.yaml",
    },
    warnings: [],
    queue_health: queueHealth(),
  };
}

function storageStatus() {
  return {
    status: "healthy",
    summary: "Configured storage paths are healthy.",
    standard_media_root: "/media",
    scratch: pathStatus({
      role: "scratch",
      display_name: "Scratch workspace",
      path: "/temp",
      status: "healthy",
      writable: true,
    }),
    data_dir: pathStatus({
      role: "data",
      display_name: "Application data",
      path: "/data",
      status: "healthy",
      writable: true,
    }),
    media_mounts: [
      pathStatus({
        role: "media",
        display_name: "Media library",
        path: "/media",
        status: "healthy",
        writable: true,
      }),
    ],
    warnings: [],
  };
}

function pathStatus({
  role,
  display_name,
  path,
  status,
  writable,
}: {
  role: string;
  display_name: string;
  path: string;
  status: string;
  writable: boolean;
}) {
  return {
    role,
    display_name,
    path,
    status,
    issue_code: "ok",
    message: `${display_name} is available.`,
    recommended_action: null,
    exists: true,
    is_directory: true,
    is_mount: true,
    readable: true,
    writable,
    same_filesystem_as_root: false,
    entry_count: 4,
    total_space_bytes: 1000,
    free_space_bytes: 500,
    free_space_ratio: 0.5,
  };
}

function jobDetail() {
  return {
    id: "job-1",
    tracked_file_id: "file-1",
    plan_snapshot_id: "plan-1",
    worker_name: "worker-local",
    status: "pending",
    attempt_count: 1,
    started_at: null,
    completed_at: null,
    failure_message: null,
    failure_category: null,
    verification_status: "pending",
    replacement_status: "pending",
    tracked_file_is_protected: false,
    requires_review: false,
    review_status: null,
    input_size_bytes: null,
    output_size_bytes: null,
    space_saved_bytes: null,
    created_at: "2026-04-20T10:02:30Z",
    updated_at: "2026-04-20T10:02:30Z",
    output_path: null,
    final_output_path: null,
    original_backup_path: null,
    execution_command: null,
    execution_stdout: null,
    execution_stderr: null,
    verification_payload: null,
    replacement_payload: null,
    replacement_failure_message: null,
    replace_in_place: true,
    require_verification: true,
    keep_original_until_verified: true,
    delete_replaced_source: false,
  };
}
