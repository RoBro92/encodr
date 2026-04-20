import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { makeSession, mockFetchRoutes, renderApp, resetBrowserState } from "../test/test-utils";

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
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/login" });

    await userEvent.clear(screen.getByLabelText(/username/i));
    await userEvent.type(screen.getByLabelText(/username/i), "admin");
    await userEvent.type(screen.getByLabelText(/password/i), "super-secure-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/operator console/i)).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem("encodr.session") ?? "{}").tokens.access_token).toBe("new-access");
  });

  it("renders the dashboard with analytics and operational sections from API data", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /operational overview/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /recent activity/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /local worker/i })).toBeInTheDocument();
    expect(screen.getByText(/1.0 gb saved/i)).toBeInTheDocument();
    expect(screen.getByText(/broken film \(2024\)\.mkv/i)).toBeInTheDocument();
  });

  it("renders the files page, filters, and detail panel", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: /\/api\/files\?/, body: { items: [{ ...fileSummary(), id: "file-1", requires_review: true, review_status: "open", is_protected: true }], limit: 100, offset: 0 } },
      { method: "GET", path: "/api/files/file-1/probe-snapshots/latest", body: probeSnapshot() },
      { method: "GET", path: "/api/files/file-1/plan-snapshots/latest", body: planSnapshot() },
      {
        method: "GET",
        path: "/api/files/file-1",
        body: {
          ...fileDetail(),
          id: "file-1",
          latest_probe_snapshot_id: "probe-1",
          latest_plan_snapshot_id: "plan-1",
          requires_review: true,
          review_status: "open",
          is_protected: true,
          protected_source: "planner",
        },
      },
    ]);

    renderApp({ route: "/files/file-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /tracked files/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText(/path search/i)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /latest plan/i })).toBeInTheDocument();
    expect(screen.getAllByText(/open in manual review/i).length).toBeGreaterThan(0);

    await userEvent.type(screen.getByLabelText(/path search/i), "Film");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
  });

  it("renders the jobs page and wires the retry action", async () => {
    const fetchMock = mockFetchRoutes([
      {
        method: "GET",
        path: /\/api\/jobs\?/,
        body: {
          items: [{ ...jobSummary(), id: "job-1", status: "failed", requires_review: true, review_status: "open", tracked_file_is_protected: true }],
          limit: 100,
          offset: 0,
        },
      },
      {
        method: "GET",
        path: "/api/jobs/job-1",
        body: { ...jobDetail(), id: "job-1", status: "failed", requires_review: true, review_status: "open", tracked_file_is_protected: true },
      },
      { method: "POST", path: "/api/jobs/job-1/retry", body: { ...jobDetail(), id: "job-2", status: "pending", attempt_count: 2 } },
      { method: "POST", path: "/api/worker/run-once", body: { processed_job: false, job_id: null, final_status: null, failure_message: null, started_at: null, completed_at: null } },
    ]);

    renderApp({ route: "/jobs/job-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /job queue/i })).toBeInTheDocument();
    expect(screen.getAllByText(/open/i).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /retry job/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/jobs/job-1/retry"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });
  });

  it("renders the workers page with local and remote inventory plus enable or disable actions", async () => {
    const fetchMock = mockFetchRoutes([
      {
        method: "GET",
        path: "/api/workers/worker-remote-1",
        body: remoteWorkerDetail(),
      },
      {
        method: "GET",
        path: "/api/workers",
        body: { items: [localWorkerSummary(), remoteWorkerSummary()] },
      },
      {
        method: "POST",
        path: "/api/workers/worker-remote-1/disable",
        body: {
          status: "disabled",
          worker: { ...remoteWorkerDetail(), enabled: false, registration_status: "disabled", health_status: "unknown" },
        },
      },
    ]);

    renderApp({ route: "/workers/worker-remote-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /worker inventory/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /remote amd worker/i })).toBeInTheDocument();
    expect(screen.getAllByText(/worker-local/i)).not.toHaveLength(0);
    expect(screen.getByText(/explicit worker capability declarations for future routing/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /disable worker/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/workers/worker-remote-1/disable"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });
  });

  it("renders the manual review page and wires decision actions", async () => {
    const fetchMock = mockFetchRoutes([
      {
        method: "GET",
        path: /\/api\/review\/items\?/,
        body: { items: [reviewItemSummary()], limit: 100, offset: 0 },
      },
      {
        method: "GET",
        path: "/api/review/items/file-1",
        body: reviewItemDetail(),
      },
      {
        method: "POST",
        path: "/api/review/items/file-1/approve",
        body: { review_item: { ...reviewItemDetail(), review_status: "approved" }, decision: reviewDecision("approved"), job: null },
      },
      {
        method: "POST",
        path: "/api/review/items/file-1/mark-protected",
        body: {
          review_item: {
            ...reviewItemDetail(),
            protected_state: { ...reviewItemDetail().protected_state, operator_protected: true, source: "planner_and_operator" },
          },
          decision: reviewDecision("mark_protected"),
          job: null,
        },
      },
      {
        method: "POST",
        path: "/api/review/items/file-1/create-job",
        body: { review_item: { ...reviewItemDetail(), review_status: "resolved" }, decision: reviewDecision("job_created"), job: { ...jobDetail(), id: "job-9", status: "pending" } },
      },
    ]);

    renderApp({ route: "/review/file-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /manual review queue/i })).toBeInTheDocument();
    expect(screen.getAllByText(/missing_english_audio/i).length).toBeGreaterThan(0);

    await userEvent.type(screen.getByLabelText(/decision note/i), "Operator approved after inspection");
    await userEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await userEvent.click(screen.getByRole("button", { name: /mark protected/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/review/items/file-1/approve"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/review/items/file-1/mark-protected"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });
  });

  it("includes the manual review entry in primary navigation", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("link", { name: /manual review/i })).toBeInTheDocument();
  });

  it("includes the workers entry in primary navigation", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("link", { name: /workers/i })).toBeInTheDocument();
  });

  it("renders the system page from sanitised operational API data", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/system", initialSession: makeSession() });
    expect(await screen.findByRole("heading", { name: /worker and storage health/i })).toBeInTheDocument();
    expect(screen.getByText(/local-only worker state, binary availability, and queue diagnostics/i)).toBeInTheDocument();
    expect(screen.getByText(/configured scratch, data, and media paths/i)).toBeInTheDocument();
  });

  it("renders degraded health states and runs the worker self-test action", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus({ status: "degraded", ffmpegStatus: "failed" }) },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus({ status: "degraded" }) },
      { method: "GET", path: "/api/system/storage", body: storageStatus({ status: "failed", scratchStatus: "failed" }) },
      {
        method: "POST",
        path: "/api/worker/self-test",
        body: {
          status: "degraded",
          summary: "Worker self-test completed with warnings.",
          worker_name: "worker-local",
          started_at: "2026-04-20T10:00:00Z",
          completed_at: "2026-04-20T10:00:05Z",
          checks: [
            { code: "ffmpeg_binary", status: "failed", message: "Binary is not discoverable or executable." },
            { code: "database", status: "healthy", message: "Database connectivity check passed." },
          ],
        },
      },
    ]);

    renderApp({ route: "/system", initialSession: makeSession() });

    const storageWarnings = await screen.findAllByText(
      /storage is reachable but needs attention|one or more configured paths are unavailable/i,
    );
    expect(storageWarnings.length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /run self-test/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/worker/self-test"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });

    expect(await screen.findByRole("heading", { name: /latest self-test/i })).toBeInTheDocument();
    expect(screen.getAllByText(/binary is not discoverable or executable/i).length).toBeGreaterThan(0);
  });

  it("renders the config page from sanitised effective config data", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/config/effective", body: effectiveConfig() },
    ]);

    renderApp({ route: "/config", initialSession: makeSession() });
    expect(await screen.findByRole("heading", { name: /effective configuration/i })).toBeInTheDocument();
    expect(screen.getByText(/default policy/i)).toBeInTheDocument();
  });

  it("renders the reports page with analytics sections from API data", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/overview", body: analyticsDashboard().overview },
      { method: "GET", path: "/api/analytics/storage", body: analyticsDashboard().storage },
      { method: "GET", path: "/api/analytics/outcomes", body: analyticsDashboard().outcomes },
      { method: "GET", path: "/api/analytics/media", body: analyticsDashboard().media },
      { method: "GET", path: "/api/analytics/recent", body: analyticsDashboard().recent },
    ]);

    renderApp({ route: "/reports", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /operational reporting/i })).toBeInTheDocument();
    expect(screen.getByText(/top failure categories/i)).toBeInTheDocument();
    expect(screen.getByText(/container distribution/i)).toBeInTheDocument();
  });

  it("shows analytics query error states cleanly", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/overview", status: 500, body: { detail: "analytics unavailable" } },
      { method: "GET", path: "/api/analytics/storage", body: analyticsDashboard().storage },
      { method: "GET", path: "/api/analytics/outcomes", body: analyticsDashboard().outcomes },
      { method: "GET", path: "/api/analytics/media", body: analyticsDashboard().media },
      { method: "GET", path: "/api/analytics/recent", body: analyticsDashboard().recent },
    ]);

    renderApp({ route: "/reports", initialSession: makeSession() });

    await waitFor(
      () => {
        expect(screen.getByRole("alert")).toHaveTextContent(/unable to load reports/i);
      },
      { timeout: 3000 },
    );
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
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
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

  it("includes the reports entry in primary navigation", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("link", { name: /reports/i })).toBeInTheDocument();
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
    operator_protected: false,
    protected_source: null,
    operator_protected_note: null,
    requires_review: false,
    review_status: null,
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
    failure_category: null,
    verification_status: "passed",
    replacement_status: "succeeded",
    tracked_file_is_protected: false,
    requires_review: false,
    review_status: null,
    input_size_bytes: 1610612736,
    output_size_bytes: 1073741824,
    space_saved_bytes: 536870912,
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

function workerStatus({
  status = "healthy",
  ffmpegStatus = "healthy",
  ffprobeStatus = "healthy",
}: {
  status?: string;
  ffmpegStatus?: string;
  ffprobeStatus?: string;
} = {}) {
  return {
    status,
    summary: status === "healthy" ? "The local worker is healthy and available." : "The local worker is available but queue health needs attention.",
    worker_name: "worker-local",
    mode: "single-node-local",
    local_only: true,
    enabled: true,
    available: ffmpegStatus === "healthy" && ffprobeStatus === "healthy",
    default_queue: "local-default",
    ffmpeg: {
      configured_path: "/usr/bin/ffmpeg",
      discoverable: ffmpegStatus === "healthy",
      exists: ffmpegStatus === "healthy",
      executable: ffmpegStatus === "healthy",
      status: ffmpegStatus,
      message: ffmpegStatus === "healthy" ? "Binary is discoverable and executable." : "Binary is not discoverable or executable.",
    },
    ffprobe: {
      configured_path: "/usr/bin/ffprobe",
      discoverable: ffprobeStatus === "healthy",
      exists: ffprobeStatus === "healthy",
      executable: ffprobeStatus === "healthy",
      status: ffprobeStatus,
      message: ffprobeStatus === "healthy" ? "Binary is discoverable and executable." : "Binary is not discoverable or executable.",
    },
    local_worker_queue: "local-default",
    last_run_started_at: "2026-04-20T10:04:30Z",
    last_run_completed_at: "2026-04-20T10:05:00Z",
    last_processed_job_id: "job-1",
    last_result_status: "completed",
    last_failure_message: null,
    processed_jobs: 4,
    capabilities: { ffmpeg: true, ffprobe: true, intel_qsv: false },
    queue_health: {
      status: status === "healthy" ? "healthy" : "degraded",
      summary: status === "healthy" ? "Queue health is within expected bounds." : "Recent job history includes failures or manual review outcomes.",
      pending_count: 1,
      running_count: 0,
      failed_count: 1,
      manual_review_count: 1,
      completed_count: 4,
      oldest_pending_age_seconds: 3600,
      last_completed_age_seconds: 300,
      recent_failed_count: 1,
      recent_manual_review_count: 1,
    },
    self_test_available: true,
  };
}

function runtimeStatus({
  status = "healthy",
}: {
  status?: string;
} = {}) {
  return {
    status,
    summary: status === "healthy" ? "Runtime health is healthy." : "Runtime health completed with warnings.",
    version: "0.1.0",
    environment: "testing",
    db_reachable: true,
    schema_reachable: true,
    auth_enabled: true,
    api_base_path: "/api",
    scratch_dir: "/tmp/scratch",
    data_dir: "/tmp/data",
    media_mounts: ["/media"],
    local_worker_enabled: true,
    user_count: 1,
    config_sources: {
      app: "/config/app.example.yaml",
      policy: "/config/policy.example.yaml",
      workers: "/config/workers.example.yaml",
    },
    warnings: status === "healthy" ? [] : ["Queue health needs attention."],
    queue_health: {
      status: status === "healthy" ? "healthy" : "degraded",
      summary: status === "healthy" ? "Queue health is within expected bounds." : "Recent job history includes failures or manual review outcomes.",
      pending_count: 1,
      running_count: 0,
      failed_count: 1,
      manual_review_count: 1,
      completed_count: 4,
      oldest_pending_age_seconds: 3600,
      last_completed_age_seconds: 300,
      recent_failed_count: 1,
      recent_manual_review_count: 1,
    },
  };
}

function storageStatus({
  status = "healthy",
  scratchStatus = "healthy",
}: {
  status?: string;
  scratchStatus?: string;
} = {}) {
  return {
    status,
    summary: status === "healthy" ? "Configured storage paths are healthy." : "One or more configured paths are unavailable.",
    scratch: {
      role: "scratch",
      path: "/tmp/scratch",
      status: scratchStatus,
      message: scratchStatus === "healthy" ? "Path is available." : "Path does not exist.",
      exists: scratchStatus === "healthy",
      is_directory: scratchStatus === "healthy",
      readable: scratchStatus === "healthy",
      writable: scratchStatus === "healthy",
      total_space_bytes: 2_000_000_000,
      free_space_bytes: scratchStatus === "healthy" ? 1_000_000_000 : null,
      free_space_ratio: scratchStatus === "healthy" ? 0.5 : null,
    },
    data_dir: {
      role: "data",
      path: "/tmp/data",
      status: "healthy",
      message: "Path is available.",
      exists: true,
      is_directory: true,
      readable: true,
      writable: true,
      total_space_bytes: 2_000_000_000,
      free_space_bytes: 1_000_000_000,
      free_space_ratio: 0.5,
    },
    media_mounts: [{
      role: "media_mount",
      path: "/media",
      status: status === "healthy" ? "healthy" : "degraded",
      message: status === "healthy" ? "Path is available." : "Path is readable but not writable.",
      exists: true,
      is_directory: true,
      readable: true,
      writable: status === "healthy",
      total_space_bytes: 2_000_000_000,
      free_space_bytes: 1_000_000_000,
      free_space_ratio: 0.5,
    }],
    warnings: status === "healthy" ? [] : ["Path does not exist."],
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
      non_4k_max_video_bitrate_mbps: 18,
      non_4k_max_width: 1920,
      four_k_mode: "strip_only",
      four_k_preserve_original_video: true,
      four_k_remove_non_english_audio: true,
      four_k_remove_non_english_subtitles: true,
    },
    workers: [
      {
        id: "local",
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
        description: "Movies profile",
        source_path: "/config/profiles/movies-default.example.yaml",
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

function localWorkerSummary() {
  return {
    id: "worker-local",
    worker_key: "worker-local",
    display_name: "worker-local",
    worker_type: "local",
    source: "projected_local",
    enabled: true,
    registration_status: "registered",
    health_status: "healthy",
    health_summary: "The local worker is healthy and available.",
    last_seen_at: "2026-04-20T10:05:00Z",
    last_heartbeat_at: "2026-04-20T10:05:00Z",
    last_registration_at: null,
    capability_summary: {
      execution_modes: ["remux", "transcode"],
      supported_video_codecs: ["hevc"],
      supported_audio_codecs: [],
      hardware_hints: ["intel_qsv"],
      binary_support: { ffmpeg: true, ffprobe: true },
      max_concurrent_jobs: 1,
      tags: ["local"],
    },
    host_summary: {
      hostname: "lxc-main",
      platform: null,
      agent_version: null,
      python_version: null,
    },
    pending_assignment_count: 1,
    last_completed_job_id: "job-1",
  };
}

function remoteWorkerSummary() {
  return {
    id: "worker-remote-1",
    worker_key: "remote-amd-01",
    display_name: "Remote AMD Worker",
    worker_type: "remote",
    source: "persisted_remote",
    enabled: true,
    registration_status: "registered",
    health_status: "healthy",
    health_summary: "Remote worker heartbeat succeeded.",
    last_seen_at: "2026-04-20T12:01:00Z",
    last_heartbeat_at: "2026-04-20T12:01:00Z",
    last_registration_at: "2026-04-20T12:00:00Z",
    capability_summary: {
      execution_modes: ["remux", "transcode"],
      supported_video_codecs: ["hevc"],
      supported_audio_codecs: [],
      hardware_hints: ["amd_gpu"],
      binary_support: { ffmpeg: true, ffprobe: true },
      max_concurrent_jobs: 1,
      tags: ["remote", "amd"],
    },
    host_summary: {
      hostname: "worker-amd",
      platform: "Linux",
      agent_version: "0.1.0",
      python_version: "3.12",
    },
    pending_assignment_count: 0,
    last_completed_job_id: null,
  };
}

function remoteWorkerDetail() {
  return {
    ...remoteWorkerSummary(),
    runtime_summary: {
      queue: "remote-amd",
      scratch_dir: "/srv/scratch",
      media_mounts: ["/srv/media"],
      last_completed_job_id: null,
    },
    binary_summary: [
      { name: "ffmpeg", configured_path: "/usr/bin/ffmpeg", discoverable: true, message: "OK" },
      { name: "ffprobe", configured_path: "/usr/bin/ffprobe", discoverable: true, message: "OK" },
    ],
    assigned_job_ids: [],
    last_processed_job_id: null,
    recent_failure_message: null,
  };
}

function reviewDecision(decisionType: string) {
  return {
    id: "decision-1",
    decision_type: decisionType,
    note: "Operator approved after inspection",
    created_at: "2026-04-20T11:00:00Z",
    created_by_user_id: "user-1",
    created_by_username: "admin",
  };
}

function reviewItemSummary() {
  return {
    id: "file-1",
    source_path: "/media/Movies/Protected Film (2024).mkv",
    review_status: "open",
    requires_review: true,
    confidence: "low",
    tracked_file: {
      ...fileSummary(),
      id: "file-1",
      source_filename: "Protected Film (2024).mkv",
      is_protected: true,
      requires_review: true,
      review_status: "open",
    },
    latest_plan: {
      ...planSnapshot(),
      should_treat_as_protected: true,
      action: "manual_review",
      warning_codes: ["ambiguous_forced_subtitle_metadata"],
    },
    latest_job: {
      ...jobSummary(),
      id: "job-7",
      status: "manual_review",
      requires_review: true,
      review_status: "open",
      tracked_file_is_protected: true,
    },
    protected_state: {
      is_protected: true,
      planner_protected: true,
      operator_protected: false,
      source: "planner",
      reason_codes: ["missing_english_audio"],
      note: null,
      updated_at: null,
      updated_by_username: null,
    },
    reasons: [
      { code: "missing_english_audio", message: "No acceptable English audio track was detected.", kind: "reason" },
    ],
    warnings: [
      { code: "ambiguous_forced_subtitle_metadata", message: "Forced subtitle tags appear ambiguous.", kind: "warning" },
    ],
    latest_probe_at: "2026-04-20T10:01:00Z",
    latest_plan_at: "2026-04-20T10:02:00Z",
    latest_job_at: "2026-04-20T10:05:00Z",
    latest_decision: null,
  };
}

function reviewItemDetail() {
  return {
    ...reviewItemSummary(),
    latest_probe_snapshot_id: "probe-1",
    latest_plan_snapshot_id: "plan-1",
    latest_job_id: "job-7",
  };
}

function analyticsDashboard() {
  return {
    overview: {
      total_tracked_files: 12,
      files_by_lifecycle: [
        { value: "planned", count: 4 },
        { value: "completed", count: 6 },
      ],
      files_by_compliance: [
        { value: "compliant", count: 5 },
        { value: "non_compliant", count: 7 },
      ],
      total_jobs: 9,
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
      verification_outcomes: [
        { value: "passed", count: 5 },
        { value: "failed", count: 2 },
      ],
      replacement_outcomes: [
        { value: "succeeded", count: 5 },
        { value: "failed", count: 1 },
      ],
      processed_under_current_policy_count: 5,
      protected_file_count: 2,
      four_k_file_count: 3,
    },
    storage: {
      total_original_size_bytes: 4294967296,
      total_output_size_bytes: 3221225472,
      total_space_saved_bytes: 1073741824,
      average_space_saved_bytes: 536870912,
      measurable_job_count: 3,
      measurable_completed_job_count: 2,
      savings_by_action: [
        { action: "remux", job_count: 1, space_saved_bytes: 268435456, average_space_saved_bytes: 268435456 },
        { action: "transcode", job_count: 1, space_saved_bytes: 805306368, average_space_saved_bytes: 805306368 },
      ],
    },
    outcomes: {
      jobs_by_status: [
        { value: "completed", count: 5 },
        { value: "failed", count: 2 },
      ],
      verification_outcomes: [
        { value: "passed", count: 5 },
        { value: "failed", count: 2 },
      ],
      replacement_outcomes: [
        { value: "succeeded", count: 5 },
        { value: "failed", count: 1 },
      ],
      top_failure_categories: [
        { category: "verification_failed", count: 2, sample_message: "The output probe data did not match the expected video codec." },
      ],
      recent_outcomes: [
        {
          job_id: "job-1",
          tracked_file_id: "file-1",
          file_name: "Example Film (2024).mkv",
          status: "completed",
          action: "remux",
          updated_at: "2026-04-20T10:15:00Z",
          failure_category: null,
          failure_message: null,
        },
      ],
    },
    media: {
      latest_probe_count: 6,
      latest_plan_count: 6,
      latest_probe_english_audio_count: 5,
      latest_probe_forced_english_subtitle_count: 2,
      latest_plan_forced_subtitle_intent_count: 2,
      latest_plan_surround_preservation_intent_count: 3,
      latest_plan_atmos_preservation_intent_count: 1,
      action_breakdown_by_resolution: [
        { resolution: "4K", actions: [{ value: "remux", count: 2 }] },
        { resolution: "Non-4K", actions: [{ value: "skip", count: 2 }, { value: "transcode", count: 2 }] },
      ],
      container_distribution: [
        { value: "mkv", count: 5 },
        { value: "mp4", count: 1 },
      ],
      video_codec_distribution: [
        { value: "hevc", count: 3 },
        { value: "h264", count: 3 },
      ],
    },
    recent: {
      recent_completed_jobs: [
        {
          job_id: "job-1",
          tracked_file_id: "file-1",
          file_name: "Example Film (2024).mkv",
          status: "completed",
          action: "remux",
          updated_at: "2026-04-20T10:15:00Z",
          failure_category: null,
          failure_message: null,
        },
      ],
      recent_failed_jobs: [
        {
          job_id: "job-2",
          tracked_file_id: "file-2",
          file_name: "Broken Film (2024).mkv",
          status: "failed",
          action: "transcode",
          updated_at: "2026-04-20T11:15:00Z",
          failure_category: "verification_failed",
          failure_message: "The output probe data did not match the expected video codec.",
        },
      ],
    },
  };
}
