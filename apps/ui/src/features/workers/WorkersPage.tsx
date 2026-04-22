import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { ScheduleWindowsEditor } from "../../components/ScheduleWindowsEditor";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useCreateRemoteWorkerOnboardingMutation,
  useDisableWorkerMutation,
  useEnableWorkerMutation,
  useSetupLocalWorkerMutation,
  useWorkerDetailQuery,
  useWorkerStatusQuery,
  useWorkersQuery,
  useUpdateWorkerPreferencesMutation,
} from "../../lib/api/hooks";
import type {
  RemoteWorkerOnboardingPayload,
  RemoteWorkerOnboardingResponse,
  WorkerPreferencePayload,
} from "../../lib/types/api";
import { formatBytes, formatDateTime, formatDurationSeconds, formatRelativeBoolean, titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

const BACKEND_OPTIONS = [
  { label: "CPU only", value: "cpu_only" },
  { label: "Prefer Intel iGPU", value: "prefer_intel_igpu" },
  { label: "Prefer NVIDIA", value: "prefer_nvidia_gpu" },
  { label: "Prefer AMD", value: "prefer_amd_gpu" },
];

export function WorkersPage() {
  const { workerId } = useParams();
  const workerStatusQuery = useWorkerStatusQuery();
  const workersQuery = useWorkersQuery();
  const detailQuery = useWorkerDetailQuery(workerId);
  const enableMutation = useEnableWorkerMutation();
  const disableMutation = useDisableWorkerMutation();
  const setupLocalWorkerMutation = useSetupLocalWorkerMutation();
  const updateWorkerPreferencesMutation = useUpdateWorkerPreferencesMutation();
  const createRemoteWorkerMutation = useCreateRemoteWorkerOnboardingMutation();
  const [showLocalSetup, setShowLocalSetup] = useState(false);
  const [showRemoteSetup, setShowRemoteSetup] = useState(false);
  const [detailDraft, setDetailDraft] = useState<WorkerPreferencePayload | null>(null);
  const [localDraft, setLocalDraft] = useState<WorkerPreferencePayload>({
    display_name: "This host",
    preferred_backend: "cpu_only",
    allow_cpu_fallback: true,
    schedule_windows: [],
  });
  const [remoteDraft, setRemoteDraft] = useState<RemoteWorkerOnboardingPayload>({
    display_name: "",
    platform: "windows",
    preferred_backend: "cpu_only",
    allow_cpu_fallback: true,
    schedule_windows: [],
  });
  const [onboardingResult, setOnboardingResult] = useState<RemoteWorkerOnboardingResponse | null>(null);
  const workerStatus = workerStatusQuery.data;
  const workers = workersQuery.data?.items ?? [];
  const localWorker = workers.find((item) => item.worker_type === "local") ?? null;
  const detail = detailQuery.data ?? null;
  const selectedBootstrap = onboardingResult && detail && onboardingResult.worker.id === detail.id ? onboardingResult : null;
  const noWorkersConfigured = workers.length === 0;
  const hardwareSummary = workerStatus
    ? workerStatus.hardware_probes
      .filter((item) => item.backend !== "cpu" && item.usable_by_ffmpeg)
      .map((item) => formatBackendLabel(item.backend))
      .join(", ")
    : "";

  useEffect(() => {
    if (detail) {
      setDetailDraft({
        display_name: detail.display_name,
        preferred_backend: detail.preferred_backend ?? "cpu_only",
        allow_cpu_fallback: detail.allow_cpu_fallback ?? true,
        schedule_windows: detail.schedule_windows ?? [],
      });
      return;
    }
    setDetailDraft(null);
  }, [detail]);

  useEffect(() => {
    if (!workerStatus) {
      return;
    }
    setLocalDraft({
      display_name: localWorker?.display_name ?? workerStatus.worker_name,
      preferred_backend: localWorker?.preferred_backend ?? workerStatus.execution_preferences.preferred_backend,
      allow_cpu_fallback: localWorker?.allow_cpu_fallback ?? workerStatus.execution_preferences.allow_cpu_fallback,
      schedule_windows: localWorker?.schedule_windows ?? [],
    });
  }, [
    localWorker?.allow_cpu_fallback,
    localWorker?.display_name,
    localWorker?.preferred_backend,
    localWorker?.schedule_windows,
    workerStatus,
  ]);

  const error = workerStatusQuery.error ?? workersQuery.error ?? detailQuery.error;
  if (workerStatusQuery.isLoading || workersQuery.isLoading) {
    return <LoadingBlock label="Loading workers" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load workers" message={error.message} />;
  }

  if (!workerStatus) {
    return <ErrorPanel title="Workers are unavailable" message="The API did not return worker status information." />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Workers"
        title="Workers"
        description="Manage execution nodes, backend preference, and worker onboarding."
        actions={(
          <div className="section-card-actions">
            <button className="button button-secondary button-small" type="button" onClick={() => {
              setShowLocalSetup((current) => !current);
              setShowRemoteSetup(false);
            }}>
              {localWorker ? "Edit this host" : "Add this host as worker"}
            </button>
            <button className="button button-primary button-small" type="button" onClick={() => {
              setShowRemoteSetup((current) => !current);
              setShowLocalSetup(false);
            }}>
              Add remote worker
            </button>
          </div>
        )}
      />

      {enableMutation.error instanceof Error ? (
        <ErrorPanel title="Enable worker failed" message={enableMutation.error.message} />
      ) : null}
      {disableMutation.error instanceof Error ? (
        <ErrorPanel title="Disable worker failed" message={disableMutation.error.message} />
      ) : null}
      {setupLocalWorkerMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to add this host as worker" message={setupLocalWorkerMutation.error.message} />
      ) : null}
      {updateWorkerPreferencesMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to save worker settings" message={updateWorkerPreferencesMutation.error.message} />
      ) : null}
      {createRemoteWorkerMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to create remote worker onboarding" message={createRemoteWorkerMutation.error.message} />
      ) : null}

      {(showLocalSetup || showRemoteSetup || noWorkersConfigured || onboardingResult) ? (
        <section className="dashboard-grid">
          <SectionCard
            title="This host"
            subtitle={localWorker ? "Local worker configuration" : "This host is not a worker yet."}
            actions={localWorker ? (
              <button
                className={`button ${localWorker.enabled ? "button-secondary" : "button-primary"} button-small`}
                type="button"
                onClick={() => (localWorker.enabled ? disableMutation.mutate(localWorker.id) : enableMutation.mutate(localWorker.id))}
                disabled={enableMutation.isPending || disableMutation.isPending}
              >
                {localWorker.enabled ? "Disable worker" : "Enable worker"}
              </button>
            ) : null}
          >
            <div className="card-stack">
              <div className="info-strip">
                <strong>{formatWorkerStateLabel(workerStatus.configuration_state)}</strong>
                <span>{workerStatus.summary}</span>
              </div>
              <KeyValueList
                items={[
                  { label: "Queue", value: workerStatus.local_worker_queue },
                  { label: "Available backends", value: hardwareSummary || "CPU only" },
                  { label: "CPU fallback", value: workerStatus.execution_preferences.allow_cpu_fallback ? "Allowed" : "Disabled" },
                  { label: "Schedule", value: localWorker?.schedule_summary ?? "Any time" },
                ]}
              />
              {showLocalSetup || !localWorker ? (
                <div className="settings-rules-fields settings-rules-fields-compact">
                  <label className="field">
                    <span>Worker label</span>
                    <input
                      aria-label="Local worker label"
                      value={localDraft.display_name ?? ""}
                      onChange={(event) => setLocalDraft((current) => ({ ...current, display_name: event.target.value }))}
                    />
                  </label>
                  <label className="field">
                    <span>Preferred backend</span>
                    <select
                      aria-label="Local worker preferred backend"
                      value={localDraft.preferred_backend}
                      onChange={(event) => setLocalDraft((current) => ({ ...current, preferred_backend: event.target.value }))}
                    >
                      {BACKEND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="field field-checkbox">
                    <span>Allow CPU fallback</span>
                    <input
                      aria-label="Local worker CPU fallback"
                      type="checkbox"
                      checked={localDraft.allow_cpu_fallback}
                      onChange={(event) => setLocalDraft((current) => ({ ...current, allow_cpu_fallback: event.target.checked }))}
                    />
                  </label>
                  <ScheduleWindowsEditor
                    label="Schedule windows"
                    value={localDraft.schedule_windows ?? []}
                    onChange={(value) => setLocalDraft((current) => ({ ...current, schedule_windows: value }))}
                  />
                </div>
              ) : null}
              {showLocalSetup || !localWorker ? (
                <div className="section-card-actions">
                  <button
                    className="button button-primary button-small"
                    type="button"
                    onClick={() => {
                      setupLocalWorkerMutation.mutate(localDraft, {
                        onSuccess: () => setShowLocalSetup(false),
                      });
                    }}
                    disabled={setupLocalWorkerMutation.isPending}
                  >
                    {setupLocalWorkerMutation.isPending ? "Saving…" : localWorker ? "Save local worker" : "Add this host as worker"}
                  </button>
                </div>
              ) : null}
            </div>
          </SectionCard>

          <SectionCard title="Remote workers" subtitle="Pair external execution nodes back to this Encodr server.">
            <div className="card-stack">
              <div className="info-strip" role="note">
                <strong>Service agent model</strong>
                <span>Remote workers run as background services. No desktop application is required.</span>
              </div>
              {showRemoteSetup || noWorkersConfigured ? (
                <div className="settings-rules-fields settings-rules-fields-compact">
                  <label className="field">
                    <span>Worker label</span>
                    <input
                      aria-label="Remote worker label"
                      value={remoteDraft.display_name ?? ""}
                      onChange={(event) => setRemoteDraft((current) => ({ ...current, display_name: event.target.value }))}
                    />
                  </label>
                  <label className="field">
                    <span>Platform</span>
                    <select
                      aria-label="Remote worker platform"
                      value={remoteDraft.platform}
                      onChange={(event) => setRemoteDraft((current) => ({ ...current, platform: event.target.value as "windows" | "linux" | "macos" }))}
                    >
                      <option value="windows">Windows</option>
                      <option value="linux">Linux</option>
                      <option value="macos">macOS</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Preferred backend</span>
                    <select
                      aria-label="Remote worker preferred backend"
                      value={remoteDraft.preferred_backend}
                      onChange={(event) => setRemoteDraft((current) => ({ ...current, preferred_backend: event.target.value }))}
                    >
                      {BACKEND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="field field-checkbox">
                    <span>Allow CPU fallback</span>
                    <input
                      aria-label="Remote worker CPU fallback"
                      type="checkbox"
                      checked={remoteDraft.allow_cpu_fallback}
                      onChange={(event) => setRemoteDraft((current) => ({ ...current, allow_cpu_fallback: event.target.checked }))}
                    />
                  </label>
                  <ScheduleWindowsEditor
                    label="Schedule windows"
                    value={remoteDraft.schedule_windows ?? []}
                    onChange={(value) => setRemoteDraft((current) => ({ ...current, schedule_windows: value }))}
                  />
                </div>
              ) : null}
              {showRemoteSetup || noWorkersConfigured ? (
                <div className="section-card-actions">
                  <button
                    className="button button-primary button-small"
                    type="button"
                    onClick={() => {
                      createRemoteWorkerMutation.mutate(remoteDraft, {
                        onSuccess: (result) => {
                          setOnboardingResult(result);
                          setShowRemoteSetup(false);
                        },
                      });
                    }}
                    disabled={createRemoteWorkerMutation.isPending}
                  >
                    {createRemoteWorkerMutation.isPending ? "Generating…" : "Generate bootstrap command"}
                  </button>
                </div>
              ) : null}
              {onboardingResult ? (
                <div className="card-stack">
                  <div className="info-strip">
                    <strong>{onboardingResult.worker.display_name}</strong>
                    <span>Pending pairing until {formatDateTime(onboardingResult.pairing_token_expires_at)}</span>
                  </div>
                  <label className="field">
                    <span>Bootstrap command</span>
                    <textarea readOnly value={onboardingResult.bootstrap_command} rows={6} />
                  </label>
                  {onboardingResult.notes.length > 0 ? (
                    <div className="list-stack">
                      {onboardingResult.notes.map((note) => (
                        <div key={note} className="list-row">
                          <span>{note}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </SectionCard>
        </section>
      ) : null}

      <section className={`jobs-review-layout${detail || (workerId && detailQuery.isLoading) ? "" : " jobs-review-layout-single"}`}>
        <SectionCard title="Workers" subtitle={`${workers.length} worker${workers.length === 1 ? "" : "s"} in view`}>
          {workers.length === 0 ? (
            <EmptyState title="No workers configured" message="Add this host as a worker or generate a remote worker bootstrap command to start taking jobs." />
          ) : (
            <div className="record-list" role="list" aria-label="Workers list">
              {workers.map((item) => {
                const isActive = item.id === workerId;
                return (
                  <Link
                    key={item.id}
                    className={`record-list-item${isActive ? " record-list-item-active" : ""}`}
                    to={APP_ROUTES.workerDetail(item.id)}
                  >
                    <div className="record-list-main">
                      <div className="record-list-heading">
                        <strong>{item.display_name}</strong>
                        <span>{item.worker_key}</span>
                      </div>
                      <div className="badge-row">
                        <StatusBadge value={item.worker_type} />
                        <StatusBadge value={item.worker_state} />
                        <StatusBadge value={item.enabled ? "enabled" : "disabled"} />
                        {item.schedule_summary ? <StatusBadge value="scheduled" /> : null}
                      </div>
                    </div>
                    <div className="record-list-meta">
                      <span className="record-list-kicker">{item.worker_type === "local" ? "This host" : "Remote worker"}</span>
                      <span>{item.current_job_id ? `${formatBackendLabel(item.current_backend)} • ${item.current_progress_percent ?? 0}%` : formatDateTime(item.last_seen_at)}</span>
                      {item.schedule_summary ? <span>{item.schedule_summary}</span> : null}
                      <span className="record-list-emphasis">{item.health_summary ?? "No health summary reported."}</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </SectionCard>

        {workerId && detailQuery.isLoading ? (
          <SectionCard title="Worker detail" subtitle="Loading worker status.">
            <LoadingBlock label="Loading worker detail" />
          </SectionCard>
        ) : detail ? (
          <SectionCard
            title="Worker detail"
            subtitle={detail.display_name}
            actions={
              detail.enabled ? (
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => disableMutation.mutate(detail.id)}
                  disabled={disableMutation.isPending}
                >
                  {disableMutation.isPending ? "Disabling…" : "Disable worker"}
                </button>
              ) : (
                <button
                  className="button button-primary button-small"
                  type="button"
                  onClick={() => enableMutation.mutate(detail.id)}
                  disabled={enableMutation.isPending}
                >
                  {enableMutation.isPending ? "Enabling…" : "Enable worker"}
                </button>
              )
            }
          >
            <div className="card-stack">
              {detail.worker_state === "remote_pending_pairing" ? (
                <div className="info-strip" role="note">
                  <strong>Pending pairing</strong>
                  <span>Run the bootstrap command on the target host, then wait for the first heartbeat.</span>
                </div>
              ) : null}

              <KeyValueList
                items={[
                  { label: "Worker key", value: detail.worker_key },
                  { label: "Type", value: <StatusBadge value={detail.worker_type} /> },
                  { label: "State", value: <StatusBadge value={detail.worker_state} /> },
                  { label: "Registration", value: <StatusBadge value={detail.registration_status} /> },
                  { label: "Health", value: <StatusBadge value={detail.health_status} /> },
                  { label: "Enabled", value: formatRelativeBoolean(detail.enabled) },
                  { label: "Preferred backend", value: formatBackendLabel(detail.preferred_backend) },
                  { label: "CPU fallback", value: detail.allow_cpu_fallback ? "Allowed" : "Disabled" },
                  { label: "Schedule", value: detail.schedule_summary ?? "Any time" },
                  { label: "Last heartbeat", value: formatDateTime(detail.last_heartbeat_at) },
                  { label: "Last seen", value: formatDateTime(detail.last_seen_at) },
                  { label: "Host", value: detail.host_summary?.hostname ?? "Not reported" },
                  { label: "Platform", value: detail.host_summary?.platform ?? "Not reported" },
                  { label: "Agent version", value: detail.host_summary?.agent_version ?? "Not reported" },
                ]}
              />

              {detailDraft ? (
                <div className="settings-rules-fields settings-rules-fields-compact">
                  <label className="field">
                    <span>Worker label</span>
                    <input
                      aria-label="Worker detail label"
                      value={detailDraft.display_name ?? ""}
                      onChange={(event) => setDetailDraft((current) => current ? { ...current, display_name: event.target.value } : current)}
                    />
                  </label>
                  <label className="field">
                    <span>Preferred backend</span>
                    <select
                      aria-label="Worker detail preferred backend"
                      value={detailDraft.preferred_backend}
                      onChange={(event) => setDetailDraft((current) => current ? { ...current, preferred_backend: event.target.value } : current)}
                    >
                      {BACKEND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="field field-checkbox">
                    <span>Allow CPU fallback</span>
                    <input
                      aria-label="Worker detail CPU fallback"
                      type="checkbox"
                      checked={detailDraft.allow_cpu_fallback}
                      onChange={(event) => setDetailDraft((current) => current ? { ...current, allow_cpu_fallback: event.target.checked } : current)}
                    />
                  </label>
                  <ScheduleWindowsEditor
                    label="Schedule windows"
                    value={detailDraft.schedule_windows ?? []}
                    onChange={(value) => setDetailDraft((current) => current ? { ...current, schedule_windows: value } : current)}
                  />
                  <div className="section-card-actions">
                    <button
                      className="button button-primary button-small"
                      type="button"
                      onClick={() => {
                        updateWorkerPreferencesMutation.mutate({
                          workerId: detail.id,
                          payload: detailDraft,
                        });
                      }}
                      disabled={updateWorkerPreferencesMutation.isPending}
                    >
                      {updateWorkerPreferencesMutation.isPending ? "Saving…" : "Save worker settings"}
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="metric-grid metric-grid-compact">
                <div className="metric-panel">
                  <span className="metric-label">Queue</span>
                  <strong>{detail.runtime_summary?.queue ?? "Not reported"}</strong>
                </div>
                <div className="metric-panel">
                  <span className="metric-label">Pending assignments</span>
                  <strong>{detail.pending_assignment_count}</strong>
                </div>
                <div className="metric-panel">
                  <span className="metric-label">Last completed job</span>
                  <strong>{detail.last_completed_job_id ?? detail.last_processed_job_id ?? "Not reported"}</strong>
                </div>
              </div>

              {detail.runtime_summary?.current_job_id || detail.runtime_summary?.telemetry ? (
                <SectionCard title="Current activity">
                  <div className="card-stack">
                    {detail.runtime_summary?.current_job_id ? (
                      <div className="metric-grid metric-grid-compact">
                        <div className="metric-panel">
                          <span className="metric-label">Current job</span>
                          <strong>{detail.runtime_summary.current_job_id}</strong>
                        </div>
                        <div className="metric-panel">
                          <span className="metric-label">Backend</span>
                          <strong>{formatBackendLabel(detail.runtime_summary.current_backend)}</strong>
                        </div>
                        <div className="metric-panel">
                          <span className="metric-label">Stage</span>
                          <strong>{detail.runtime_summary.current_stage ? titleCase(detail.runtime_summary.current_stage) : "Running"}</strong>
                        </div>
                        <div className="metric-panel">
                          <span className="metric-label">Progress</span>
                          <strong>
                            {detail.runtime_summary.current_progress_percent != null
                              ? `${detail.runtime_summary.current_progress_percent}%`
                              : "Starting"}
                          </strong>
                        </div>
                      </div>
                    ) : null}
                    {detail.runtime_summary?.telemetry ? (
                      <TelemetrySummary telemetry={detail.runtime_summary.telemetry} />
                    ) : null}
                  </div>
                </SectionCard>
              ) : null}

              {detail.capability_summary.execution_modes.length > 0 ||
              detail.capability_summary.supported_video_codecs.length > 0 ||
              detail.capability_summary.hardware_hints.length > 0 ||
              detail.capability_summary.tags.length > 0 ? (
                <SectionCard title="Capabilities">
                  <KeyValueList
                    items={[
                      { label: "Execution modes", value: detail.capability_summary.execution_modes.join(", ") || "None" },
                      { label: "Video codecs", value: detail.capability_summary.supported_video_codecs.join(", ") || "None declared" },
                      { label: "Hardware", value: detail.capability_summary.hardware_hints.join(", ") || "None declared" },
                      { label: "Tags", value: detail.capability_summary.tags.join(", ") || "None" },
                      { label: "Max concurrency", value: detail.capability_summary.max_concurrent_jobs ?? "Not reported" },
                    ]}
                  />
                </SectionCard>
              ) : null}

              {detail.binary_summary.length > 0 ? (
                <SectionCard title="Binary checks">
                  <div className="list-stack">
                    {detail.binary_summary.map((binary) => (
                      <div key={binary.name} className="list-row">
                        <div>
                          <strong>{binary.name}</strong>
                          <p>{binary.configured_path ?? "No configured path reported"}</p>
                          <p>{binary.message ?? "No message reported"}</p>
                        </div>
                        <StatusBadge value={binary.discoverable == null ? "unknown" : binary.discoverable ? "healthy" : "failed"} />
                      </div>
                    ))}
                  </div>
                </SectionCard>
              ) : null}

              {selectedBootstrap ? (
                <SectionCard title="Bootstrap command" subtitle="Run this on the target worker host.">
                  <div className="card-stack">
                    <label className="field">
                      <span>Command</span>
                      <textarea readOnly value={selectedBootstrap.bootstrap_command} rows={6} />
                    </label>
                    {selectedBootstrap.notes.map((note) => (
                      <div key={note} className="info-strip" role="note">
                        <span>{note}</span>
                      </div>
                    ))}
                  </div>
                </SectionCard>
              ) : null}

              {detail.recent_jobs.length > 0 ? (
                <SectionCard title="Recent jobs">
                  <div className="list-stack">
                    {detail.recent_jobs.map((job) => (
                      <div key={job.job_id} className="list-row">
                        <div>
                          <strong>{job.source_filename ?? job.job_id}</strong>
                          <p>
                            {formatBackendLabel(job.actual_execution_backend ?? job.requested_execution_backend)}
                            {job.backend_fallback_used ? " • CPU fallback used" : ""}
                          </p>
                          <p>
                            {formatDateTime(job.completed_at)}
                            {job.duration_seconds != null ? ` • ${formatDurationSeconds(job.duration_seconds)}` : ""}
                          </p>
                          {job.failure_message ? <p>{job.failure_message}</p> : null}
                        </div>
                        <StatusBadge value={job.status} />
                      </div>
                    ))}
                  </div>
                </SectionCard>
              ) : null}
            </div>
          </SectionCard>
        ) : workers.length > 0 ? (
          <SectionCard title="Worker detail" subtitle="Select a worker to view health, telemetry, and backend settings.">
            <EmptyState title="No worker selected" message="Choose a worker from the list to inspect its health or change its backend preference." />
          </SectionCard>
        ) : null}
      </section>
    </div>
  );
}

function TelemetrySummary({ telemetry }: { telemetry: Record<string, unknown> }) {
  const gpu = telemetry.gpu as Record<string, unknown> | null | undefined;
  return (
    <div className="metric-grid metric-grid-compact">
      <div className="metric-panel">
        <span className="metric-label">CPU</span>
        <strong>{formatPercentValue(telemetry.cpu_usage_percent)}</strong>
      </div>
      <div className="metric-panel">
        <span className="metric-label">Process CPU</span>
        <strong>{formatPercentValue(telemetry.process_cpu_usage_percent)}</strong>
      </div>
      <div className="metric-panel">
        <span className="metric-label">Memory</span>
        <strong>{formatPercentValue(telemetry.memory_usage_percent)}</strong>
      </div>
      <div className="metric-panel">
        <span className="metric-label">Process memory</span>
        <strong>{formatBytes(readNumber(telemetry.process_memory_bytes))}</strong>
      </div>
      <div className="metric-panel">
        <span className="metric-label">CPU temp</span>
        <strong>{formatTemperature(telemetry.cpu_temperature_c)}</strong>
      </div>
      <div className="metric-panel">
        <span className="metric-label">GPU</span>
        <strong>{formatGpuMetric(gpu)}</strong>
      </div>
    </div>
  );
}

function formatPercentValue(value: unknown) {
  const parsed = readNumber(value);
  return parsed == null ? "Unavailable" : `${parsed.toFixed(1)}%`;
}

function formatTemperature(value: unknown) {
  const parsed = readNumber(value);
  return parsed == null ? "Unavailable" : `${parsed.toFixed(1)}°C`;
}

function formatGpuMetric(gpu: Record<string, unknown> | null | undefined) {
  if (!gpu) {
    return "Unavailable";
  }
  const usage = readNumber(gpu.usage_percent);
  const vendor = typeof gpu.vendor === "string" ? gpu.vendor : "GPU";
  if (usage != null) {
    return `${vendor} ${usage.toFixed(1)}%`;
  }
  const temperature = readNumber(gpu.temperature_c);
  if (temperature != null) {
    return `${vendor} ${temperature.toFixed(1)}°C`;
  }
  return typeof gpu.message === "string" ? gpu.message : vendor;
}

function readNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatBackendLabel(value: string | null | undefined) {
  if (!value) {
    return "Not reported";
  }
  return {
    cpu: "CPU",
    cpu_only: "CPU",
    intel_igpu: "Intel iGPU",
    prefer_intel_igpu: "Intel iGPU",
    nvidia_gpu: "NVIDIA",
    prefer_nvidia_gpu: "NVIDIA",
    amd_gpu: "AMD",
    prefer_amd_gpu: "AMD",
  }[value] ?? value.replace(/_/g, " ");
}

function formatWorkerStateLabel(value: string | null | undefined) {
  if (!value) {
    return "Unknown";
  }
  return {
    local_not_configured: "Not configured",
    local_configured_disabled: "Configured but disabled",
    local_healthy: "Healthy",
    local_degraded: "Degraded",
    local_unavailable: "Unavailable",
    remote_pending_pairing: "Pending pairing",
    remote_registered: "Registered",
    remote_healthy: "Healthy",
    remote_degraded: "Degraded",
    remote_offline: "Offline",
    remote_disabled: "Disabled",
  }[value] ?? titleCase(value);
}
