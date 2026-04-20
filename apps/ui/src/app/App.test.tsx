import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderApp, makeSession, mockFetchRoutes, resetBrowserState } from "../test/test-utils";

describe("Encodr UI shell", () => {
  beforeEach(() => {
    resetBrowserState();
  });

  afterEach(() => {
    resetBrowserState();
  });

  it("shows the login screen when an unauthenticated user opens a protected route", async () => {
    renderApp({ route: "/" });

    expect(await screen.findByRole("heading", { name: /sign in to the operator console/i })).toBeInTheDocument();
  });

  it("signs in, stores the session, and loads the app shell", async () => {
    mockFetchRoutes([
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
      { method: "GET", path: /\/api\/files\?/, body: { items: [], limit: 200, offset: 0 } },
      { method: "GET", path: /\/api\/jobs\?/, body: { items: [], limit: 50, offset: 0 } },
      {
        method: "GET",
        path: "/api/worker/status",
        body: {
          worker_name: "worker-local",
          local_only: true,
          default_queue: "local-default",
          ffmpeg: { configured_path: "/usr/bin/ffmpeg", discoverable: true, exists: true, executable: true },
          ffprobe: { configured_path: "/usr/bin/ffprobe", discoverable: true, exists: true, executable: true },
          local_worker_enabled: true,
          local_worker_queue: "local-default",
          last_run_started_at: null,
          last_run_completed_at: null,
          last_processed_job_id: null,
          last_result_status: null,
          last_failure_message: null,
          processed_jobs: 0,
          capabilities: { ffmpeg: true, ffprobe: true },
        },
      },
      {
        method: "GET",
        path: "/api/system/runtime",
        body: {
          version: "0.1.0",
          environment: "testing",
          db_reachable: true,
          auth_enabled: true,
          api_base_path: "/api",
          scratch_dir: "/tmp/scratch",
          data_dir: "/tmp/data",
          media_mounts: ["/media"],
        },
      },
      {
        method: "GET",
        path: "/api/system/storage",
        body: {
          scratch: { path: "/tmp/scratch", exists: true, is_directory: true, readable: true, writable: true },
          data_dir: { path: "/tmp/data", exists: true, is_directory: true, readable: true, writable: true },
          media_mounts: [{ path: "/media", exists: true, is_directory: true, readable: true, writable: false }],
        },
      },
    ]);

    renderApp({ route: "/login" });

    await userEvent.clear(screen.getByLabelText(/username/i));
    await userEvent.type(screen.getByLabelText(/username/i), "admin");
    await userEvent.type(screen.getByLabelText(/password/i), "super-secure-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/operator console/i)).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem("encodr.session") ?? "{}").tokens.access_token).toBe("new-access");
  });

  it("renders the dashboard with operational sections from API data", async () => {
    mockFetchRoutes([
      { method: "GET", path: /\/api\/files\?/, body: { items: [{ ...fileSummary(), id: "file-1" }], limit: 200, offset: 0 } },
      { method: "GET", path: /\/api\/jobs\?/, body: { items: [jobSummary()], limit: 50, offset: 0 } },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /operational overview/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /latest jobs/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /local worker/i })).toBeInTheDocument();
    expect(screen.getByText("job-1")).toBeInTheDocument();
  });

  it("renders the files page, filters, and detail panel", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: /\/api\/files\?/, body: { items: [{ ...fileSummary(), id: "file-1" }], limit: 100, offset: 0 } },
      { method: "GET", path: "/api/files/file-1/probe-snapshots/latest", body: probeSnapshot() },
      { method: "GET", path: "/api/files/file-1/plan-snapshots/latest", body: planSnapshot() },
      { method: "GET", path: "/api/files/file-1", body: { ...fileDetail(), id: "file-1", latest_probe_snapshot_id: "probe-1", latest_plan_snapshot_id: "plan-1" } },
    ]);

    renderApp({ route: "/files/file-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /tracked files/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText(/path search/i)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /latest plan/i })).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/path search/i), "Film");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
  });

  it("renders the jobs page and wires the retry action", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: /\/api\/jobs\?/, body: { items: [{ ...jobSummary(), id: "job-1", status: "failed" }], limit: 100, offset: 0 } },
      { method: "GET", path: "/api/jobs/job-1", body: { ...jobDetail(), id: "job-1", status: "failed" } },
      { method: "POST", path: "/api/jobs/job-1/retry", body: { ...jobDetail(), id: "job-2", status: "pending", attempt_count: 2 } },
      { method: "POST", path: "/api/worker/run-once", body: { processed_job: false, job_id: null, final_status: null, failure_message: null, started_at: null, completed_at: null } },
    ]);

    renderApp({ route: "/jobs/job-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /job queue/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry job/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/jobs/job-1/retry"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });
  });

  it("renders the system page from sanitised operational API data", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/system", initialSession: makeSession() });
    expect(await screen.findByRole("heading", { name: /worker and runtime status/i })).toBeInTheDocument();
    expect(screen.getByText(/database reachable/i)).toBeInTheDocument();
  });

  it("renders the config page from sanitised effective config data", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/config/effective", body: effectiveConfig() },
    ]);

    renderApp({ route: "/config", initialSession: makeSession() });
    expect(await screen.findByRole("heading", { name: /effective configuration/i })).toBeInTheDocument();
    expect(screen.getByText(/default policy/i)).toBeInTheDocument();
  });

  it("clears the session and returns to login after an unauthorised API response", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/config/effective", status: 401, body: { detail: "Invalid authentication credentials." } },
      { method: "POST", path: "/api/auth/refresh", status: 401, body: { detail: "The refresh token is invalid or expired." } },
    ]);

    window.localStorage.setItem("encodr.session", JSON.stringify(makeSession()));
    renderApp({ route: "/config", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /sign in to the operator console/i })).toBeInTheDocument();
    expect(window.localStorage.getItem("encodr.session")).toBeNull();
  });

  it("wires probe, plan, and run-once actions and surfaces success", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: /\/api\/files\?/, body: { items: [], limit: 200, offset: 0 } },
      { method: "GET", path: /\/api\/jobs\?/, body: { items: [], limit: 50, offset: 0 } },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      { method: "POST", path: "/api/files/probe", body: { tracked_file: fileSummary(), latest_probe_snapshot: probeSnapshot() } },
      { method: "POST", path: "/api/files/plan", body: { tracked_file: fileSummary(), latest_probe_snapshot: probeSnapshot(), latest_plan_snapshot: planSnapshot() } },
      { method: "POST", path: "/api/worker/run-once", body: { processed_job: true, job_id: "job-1", final_status: "completed", failure_message: null, started_at: null, completed_at: null } },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /operational overview/i })).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/probe source path/i), "/media/Movies/Probe.mkv");
    await userEvent.click(screen.getByRole("button", { name: /probe file/i }));
    await userEvent.type(screen.getByLabelText(/plan source path/i), "/media/Movies/Plan.mkv");
    await userEvent.click(screen.getByRole("button", { name: /plan file/i }));
    await userEvent.click(screen.getByRole("button", { name: /run worker once/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/files/probe"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/files/plan"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/worker/run-once"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });

    expect(await screen.findByText(/processed job job-1/i)).toBeInTheDocument();
  });
});

function fileSummary() {
  return {
    id: "file-1",
    source_path: "/media/Movies/Example Film (2024).mkv",
    source_filename: "Example Film (2024).mkv",
    source_extension: "mkv",
    source_directory: "/media/Movies",
    last_observed_size: 8123456789,
    last_observed_modified_time: null,
    fingerprint_placeholder: null,
    is_4k: false,
    lifecycle_state: "planned",
    compliance_state: "non_compliant",
    is_protected: false,
    last_processed_policy_version: 1,
    last_processed_profile_name: null,
    created_at: "2026-04-20T10:00:00Z",
    updated_at: "2026-04-20T10:05:00Z",
  };
}

function fileDetail() {
  return {
    ...fileSummary(),
    latest_probe_snapshot_id: "probe-1",
    latest_plan_snapshot_id: "plan-1",
  };
}

function probeSnapshot() {
  return {
    id: "probe-1",
    tracked_file_id: "file-1",
    schema_version: 1,
    created_at: "2026-04-20T10:01:00Z",
    file_name: "Example Film (2024).mkv",
    format_name: "matroska,webm",
    duration_seconds: 7200,
    size_bytes: 8123456789,
    video_stream_count: 1,
    audio_stream_count: 2,
    subtitle_stream_count: 1,
    is_4k: false,
    payload: { container: { format_name: "matroska,webm" } },
  };
}

function planSnapshot() {
  return {
    id: "plan-1",
    tracked_file_id: "file-1",
    probe_snapshot_id: "probe-1",
    action: "remux",
    confidence: "high",
    policy_version: 1,
    profile_name: null,
    is_already_compliant: false,
    should_treat_as_protected: false,
    created_at: "2026-04-20T10:02:00Z",
    reason_codes: ["non_english_audio_removed"],
    warning_codes: [],
    selected_audio_stream_indices: [1],
    selected_subtitle_stream_indices: [2],
    reasons: [{ code: "non_english_audio_removed", message: "Non-English audio would be removed." }],
    warnings: [],
    selected_streams: { audio_stream_indices: [1], subtitle_stream_indices: [2] },
    payload: { action: "remux" },
  };
}

function jobSummary() {
  return {
    id: "job-1",
    tracked_file_id: "file-1",
    plan_snapshot_id: "plan-1",
    worker_name: "worker-local",
    status: "completed",
    attempt_count: 1,
    started_at: "2026-04-20T10:03:00Z",
    completed_at: "2026-04-20T10:04:00Z",
    failure_message: null,
    verification_status: "passed",
    replacement_status: "succeeded",
    created_at: "2026-04-20T10:02:30Z",
    updated_at: "2026-04-20T10:04:00Z",
  };
}

function jobDetail() {
  return {
    ...jobSummary(),
    output_path: "/scratch/job-1.mkv",
    final_output_path: "/media/Movies/Example Film (2024).mkv",
    original_backup_path: null,
    execution_command: ["/usr/bin/ffmpeg", "-y"],
    execution_stdout: "",
    execution_stderr: "",
    verification_payload: { status: "passed" },
    replacement_payload: { status: "succeeded" },
    replacement_failure_message: null,
    replace_in_place: true,
    require_verification: true,
    keep_original_until_verified: true,
    delete_replaced_source: false,
  };
}

function workerStatus() {
  return {
    worker_name: "worker-local",
    local_only: true,
    default_queue: "local-default",
    ffmpeg: { configured_path: "/usr/bin/ffmpeg", discoverable: true, exists: true, executable: true },
    ffprobe: { configured_path: "/usr/bin/ffprobe", discoverable: true, exists: true, executable: true },
    local_worker_enabled: true,
    local_worker_queue: "local-default",
    last_run_started_at: "2026-04-20T10:04:30Z",
    last_run_completed_at: "2026-04-20T10:05:00Z",
    last_processed_job_id: "job-1",
    last_result_status: "completed",
    last_failure_message: null,
    processed_jobs: 4,
    capabilities: { ffmpeg: true, ffprobe: true, intel_qsv: false },
  };
}

function runtimeStatus() {
  return {
    version: "0.1.0",
    environment: "testing",
    db_reachable: true,
    auth_enabled: true,
    api_base_path: "/api",
    scratch_dir: "/tmp/scratch",
    data_dir: "/tmp/data",
    media_mounts: ["/media"],
  };
}

function storageStatus() {
  return {
    scratch: { path: "/tmp/scratch", exists: true, is_directory: true, readable: true, writable: true },
    data_dir: { path: "/tmp/data", exists: true, is_directory: true, readable: true, writable: true },
    media_mounts: [{ path: "/media", exists: true, is_directory: true, readable: true, writable: false }],
  };
}

function effectiveConfig() {
  return {
    app_name: "encodr",
    environment: "testing",
    timezone: "Europe/London",
    scratch_dir: "/tmp/scratch",
    data_dir: "/tmp/data",
    output: { return_to_original_folder: true, default_container: "mkv" },
    auth: {
      enabled: true,
      session_mode: "jwt",
      access_token_ttl_minutes: 30,
      refresh_token_ttl_days: 14,
      access_token_algorithm: "HS256",
    },
    policy_version: 1,
    policy_name: "default policy",
    profile_names: ["movies-default", "tv-default"],
    audio: {
      keep_languages: ["eng"],
      preserve_best_surround: true,
      preserve_atmos_capable: true,
      preferred_codecs: ["truehd", "eac3"],
      allow_commentary: false,
      max_tracks_to_keep: 2,
    },
    subtitles: {
      keep_languages: ["eng"],
      keep_forced_languages: ["eng"],
      keep_commentary: false,
      keep_hearing_impaired: true,
    },
    video: {
      output_container: "mkv",
      non_4k_preferred_codec: "hevc",
      non_4k_allow_transcode: true,
      non_4k_max_video_bitrate_mbps: 12,
      non_4k_max_width: 1920,
      four_k_mode: "strip_only",
      four_k_preserve_original_video: true,
      four_k_remove_non_english_audio: true,
      four_k_remove_non_english_subtitles: true,
    },
    workers: [
      {
        id: "worker-local",
        type: "local",
        enabled: true,
        queue: "local-default",
        host_or_endpoint: "localhost",
        max_concurrent_jobs: 1,
        capabilities: { ffmpeg: true, ffprobe: true },
      },
    ],
    profiles: [
      {
        name: "movies-default",
        description: "Movie profile",
        source_path: "/config/profiles/movies-default.yaml",
        path_prefixes: ["/media/Movies"],
      },
    ],
    sources: {
      app: {
        requested_path: "/config/app.yaml",
        resolved_path: "/config/app.example.yaml",
        used_example_fallback: true,
        from_environment: false,
      },
    },
  };
}
