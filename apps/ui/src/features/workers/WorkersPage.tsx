import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CollapsibleSection } from "../../components/CollapsibleSection";
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
  useDeleteWorkerMutation,
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
  WorkerInventorySummary,
  WorkerInventoryDetail,
  WorkerPreferencePayload,
  WorkerRemovalResponse,
  WorkerStatus,
} from "../../lib/types/api";
import {
  formatBytes,
  formatDateTime,
  formatDurationSeconds,
  titleCase,
} from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

const BACKEND_OPTIONS = [
  { label: "CPU only", value: "cpu_only" },
  { label: "Prefer Intel iGPU", value: "prefer_intel_igpu" },
  { label: "Prefer NVIDIA", value: "prefer_nvidia_gpu" },
  { label: "Prefer AMD", value: "prefer_amd_gpu" },
] as const;

const PLATFORM_OPTIONS = [
  { label: "Windows", value: "windows" },
  { label: "Linux", value: "linux" },
  { label: "macOS", value: "macos" },
] as const;

type AddWorkerMode = "choose" | "local" | "remote";
type PathMappingDraft = {
  label?: string | null;
  server_path: string;
  worker_path: string;
};

type WorkerStatusRollupResult = {
  badge: "healthy" | "degraded" | "failed" | string;
  message: string;
  compactMessage: string;
  attentionMessage: string | null;
};

const EMPTY_PATH_MAPPING: PathMappingDraft = {
  label: "",
  server_path: "",
  worker_path: "",
};

function blankLocalDraft(workerName: string): WorkerPreferencePayload {
  return {
    display_name: workerName,
    preferred_backend: "cpu_only",
    allow_cpu_fallback: true,
    max_concurrent_jobs: 1,
    schedule_windows: [],
    scratch_path: "",
    path_mappings: [],
  };
}

function blankRemoteDraft(): RemoteWorkerOnboardingPayload {
  return {
    display_name: "",
    platform: "windows",
    preferred_backend: "cpu_only",
    allow_cpu_fallback: true,
    max_concurrent_jobs: 1,
    schedule_windows: [],
    scratch_path: "",
    path_mappings: [],
  };
}

function workerDraftFromDetail(detail: WorkerInventoryDetail): WorkerPreferencePayload {
  const pathMappings = detail.path_mappings ?? detail.runtime_summary?.path_mappings ?? [];
  return {
    display_name: detail.display_name,
    preferred_backend: detail.preferred_backend ?? "cpu_only",
    allow_cpu_fallback: detail.allow_cpu_fallback ?? true,
    max_concurrent_jobs: detail.max_concurrent_jobs ?? 1,
    schedule_windows: detail.schedule_windows ?? [],
    scratch_path: detail.scratch_path ?? detail.runtime_summary?.scratch_dir ?? "",
    path_mappings: pathMappings.map((mapping) => ({
      label: mapping.label,
      server_path: mapping.server_path,
      worker_path: mapping.worker_path,
    })),
  };
}

export function WorkersPage() {
  const { workerId } = useParams();
  const navigate = useNavigate();
  const workerStatusQuery = useWorkerStatusQuery();
  const workersQuery = useWorkersQuery();
  const detailQuery = useWorkerDetailQuery(workerId);
  const enableMutation = useEnableWorkerMutation();
  const disableMutation = useDisableWorkerMutation();
  const setupLocalWorkerMutation = useSetupLocalWorkerMutation();
  const updateWorkerPreferencesMutation = useUpdateWorkerPreferencesMutation();
  const createRemoteWorkerMutation = useCreateRemoteWorkerOnboardingMutation();
  const deleteWorkerMutation = useDeleteWorkerMutation();

  const [isAddWorkerOpen, setIsAddWorkerOpen] = useState(false);
  const [isAddWorkerMenuOpen, setIsAddWorkerMenuOpen] = useState(false);
  const [addWorkerMode, setAddWorkerMode] = useState<AddWorkerMode>("choose");
  const [localDraft, setLocalDraft] = useState<WorkerPreferencePayload>(blankLocalDraft("This host"));
  const [remoteDraft, setRemoteDraft] = useState<RemoteWorkerOnboardingPayload>(blankRemoteDraft());
  const [editingWorker, setEditingWorker] = useState<WorkerInventoryDetail | null>(null);
  const [editDraft, setEditDraft] = useState<WorkerPreferencePayload | null>(null);
  const [onboardingResult, setOnboardingResult] = useState<RemoteWorkerOnboardingResponse | null>(null);
  const [removalResult, setRemovalResult] = useState<WorkerRemovalResponse | null>(null);

  const workerStatus = workerStatusQuery.data;
  const workers = workersQuery.data?.items ?? [];
  const detail = detailQuery.data ?? null;
  const localCapabilities = useMemo(
    () =>
      (workerStatus?.hardware_probes ?? [])
        .filter((item) => item.backend !== "cpu")
        .filter((item) => item.preference_key === localDraft.preferred_backend)
        .map((item) => ({
          backend: item.backend,
          usable: item.usable_by_ffmpeg,
          message: item.message,
        })),
    [localDraft.preferred_backend, workerStatus?.hardware_probes],
  );

  useEffect(() => {
    if (!workerStatus) {
      return;
    }
    setLocalDraft((current) => ({
      ...current,
      display_name: workerStatus.worker_name,
      scratch_path: readScratchPath(workerStatus.scratch_path) ?? current.scratch_path,
      max_concurrent_jobs: recommendedLocalConcurrency(workerStatus),
    }));
  }, [workerStatus]);

  useEffect(() => {
    if (!detail) {
      return;
    }
    setEditDraft(workerDraftFromDetail(detail));
  }, [detail]);

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

  const noWorkersConfigured = workers.length === 0;
  const detailPathMappings = detail?.path_mappings ?? detail?.runtime_summary?.path_mappings ?? [];
  const detailRecentJobs = detail?.recent_jobs ?? [];
  const localWorkerStatus = detail?.worker_type === "local" ? workerStatus : null;
  const detailPrimaryIssues = detail ? buildWorkerPrimaryIssues(detail, localWorkerStatus) : [];
  const detailCurrentBackend = detail?.current_backend ?? detail?.runtime_summary?.current_backend ?? null;
  const cpuFallbackActive = Boolean(
    detail?.preferred_backend &&
    detailCurrentBackend &&
    detail.preferred_backend !== "cpu_only" &&
    detailCurrentBackend === "cpu",
  );
  const localBackendProbes = localWorkerStatus?.hardware_probes ?? [];
  const configuredBackendProbe = detail?.worker_type === "local"
    ? localBackendProbes.find((item) => item.preference_key === detail.preferred_backend)
    : null;
  const detailStatusRollup = detail ? buildWorkerStatusRollup(detail, localWorkerStatus) : null;
  const detailAttentionTitle = detailStatusRollup?.badge === "degraded"
    ? "Backend Degraded"
    : detailStatusRollup?.badge === "failed"
      ? "Backend Failed"
      : "Attention";
  const detailAttentionMessage = detailStatusRollup?.attentionMessage
    ?? (detailPrimaryIssues.length > 0 ? detailPrimaryIssues.join(" • ") : null);
  const selectedHardwareBackendProbe = configuredBackendProbe && configuredBackendProbe.backend !== "cpu"
    ? configuredBackendProbe
    : null;
  const selectedRuntimeDevices = selectedHardwareBackendProbe?.device_paths ?? [];

  function openAddWorker(mode: Exclude<AddWorkerMode, "choose">) {
    setIsAddWorkerMenuOpen(false);
    setIsAddWorkerOpen(true);
    setAddWorkerMode(mode);
    setOnboardingResult(null);
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Workers"
        title="Workers"
        description="Add execution nodes, pair remote agents, and manage backend, concurrency, schedule, and storage access per worker."
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
      {deleteWorkerMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to remove worker" message={deleteWorkerMutation.error.message} />
      ) : null}

      <SectionCard
        title="Worker inventory"
        subtitle={noWorkersConfigured ? "No workers configured yet." : `${workers.length} worker${workers.length === 1 ? "" : "s"} configured`}
        actions={(
          <div className="worker-add-menu">
            <button
              className="button button-primary button-small"
              type="button"
              aria-haspopup="menu"
              aria-expanded={isAddWorkerMenuOpen}
              onClick={() => setIsAddWorkerMenuOpen((current) => !current)}
            >
              + Add Worker
            </button>
            {isAddWorkerMenuOpen ? (
              <div className="worker-add-menu-panel" role="menu">
                <button type="button" role="menuitem" onClick={() => openAddWorker("local")}>
                  Add Local Worker
                </button>
                <button type="button" role="menuitem" onClick={() => openAddWorker("remote")}>
                  Add Remote Worker
                </button>
              </div>
            ) : null}
          </div>
        )}
      >
        {noWorkersConfigured ? (
          <EmptyState
            title="No workers configured"
            message="Add this host as a worker or pair a remote worker when you are ready to give Encodr execution capacity."
          />
        ) : (
          <div className="record-list worker-inventory-list" role="list" aria-label="Workers list">
            {workers.map((item) => {
              const isActive = item.id === workerId;
              const itemLocalWorkerStatus = item.worker_type === "local" && (!workerStatus.worker_id || workerStatus.worker_id === item.id)
                ? workerStatus
                : null;
              const itemStatusRollup = buildWorkerStatusRollup(item, itemLocalWorkerStatus);
              return (
                <Link
                  key={item.id}
                  className={`record-list-item worker-inventory-row${isActive ? " record-list-item-active" : ""}`}
                  to={APP_ROUTES.workerDetail(item.id)}
                >
                  <div className="worker-inventory-main">
                    <div className="record-list-heading">
                      <strong>{item.display_name}</strong>
                      <span>{item.worker_key}</span>
                    </div>
                    <div className="badge-row">
                      <StatusBadge value={item.worker_type} />
                      <StatusBadge value={item.worker_state} />
                      <StatusBadge value={item.enabled ? "enabled" : "disabled"} />
                      <StatusBadge value={itemStatusRollup.badge} />
                    </div>
                  </div>
                  <div className="worker-inventory-stats">
                    <WorkerInventoryStat label="Worker" value={item.worker_type === "local" ? "This host" : "Remote"} />
                    <WorkerInventoryStat label="Backend" value={formatBackendLabel(item.preferred_backend)} />
                    <WorkerInventoryStat label="Concurrency" value={formatConcurrencyLabel(item)} />
                    <WorkerInventoryStat label="Schedule" value={item.schedule_summary ?? "Any time"} />
                    <WorkerInventoryStat
                      label="Status message"
                      value={<WorkerStatusRollupView rollup={itemStatusRollup} />}
                      clamp
                    />
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </SectionCard>

      {workerId && detailQuery.isLoading ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Worker detail">
          <section className="modal-panel">
            <div className="section-card-header">
              <div>
                <h2>Worker detail</h2>
                <p>Loading the selected worker.</p>
              </div>
              <div className="section-card-actions">
                <button className="button button-secondary button-small" type="button" onClick={() => navigate(APP_ROUTES.workers)}>
                  Close
                </button>
              </div>
            </div>
            <LoadingBlock label="Loading worker detail" />
          </section>
        </div>
      ) : null}

      {detail ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Worker detail">
          <section className="modal-panel modal-panel-worker-detail worker-detail-modal">
            <div className="section-card-header">
              <div className="worker-detail-header-copy">
                <h2>Worker detail</h2>
                <h3>{detail.worker_key}</h3>
                <p>{detail.display_name}</p>
              </div>
              <div className="section-card-actions">
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => setEditingWorker(detail)}
                >
                  Edit worker
                </button>
                {detail.enabled ? (
                  <button
                    className="button button-secondary button-small"
                    type="button"
                    onClick={() => disableMutation.mutate(detail.id)}
                    disabled={disableMutation.isPending}
                  >
                    {disableMutation.isPending ? "Disabling…" : "Disable"}
                  </button>
                ) : (
                  <button
                    className="button button-primary button-small"
                    type="button"
                    onClick={() => enableMutation.mutate(detail.id)}
                    disabled={enableMutation.isPending}
                  >
                    {enableMutation.isPending ? "Enabling…" : "Enable"}
                  </button>
                )}
                <button className="button button-secondary button-small" type="button" onClick={() => navigate(APP_ROUTES.workers)}>
                  Close
                </button>
              </div>
            </div>

            <div className="card-stack">
              <div className="worker-detail-tag-row" aria-label="Worker summary">
                <WorkerDetailTag label="Type" value={titleCase(detail.worker_type)} />
                <WorkerDetailTag
                  label="Backend"
                  value={cpuFallbackActive ? "CPU fallback" : formatBackendLabel(detailCurrentBackend ?? detail.preferred_backend)}
                />
                <WorkerDetailTag
                  label="Status"
                  value={<StatusBadge value={!detail.enabled ? "disabled" : detailStatusRollup?.badge ?? detail.health_status} />}
                />
              </div>

              {detailAttentionMessage ? (
                <div className="worker-attention-banner" role="note">
                  <span className="worker-attention-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" focusable="false">
                      <path d="M10.3 4.2 2.7 17.4A2 2 0 0 0 4.4 20h15.2a2 2 0 0 0 1.7-2.6L13.7 4.2a2 2 0 0 0-3.4 0Z" />
                      <path d="M12 9v4" />
                      <path d="M12 17h.01" />
                    </svg>
                  </span>
                  <div>
                    <strong>{detailAttentionTitle}</strong>
                    <span>{detailAttentionMessage}</span>
                  </div>
                </div>
              ) : null}

              {detail.worker_state === "remote_pending_pairing" ? (
                <div className="info-strip info-strip-warning" role="note">
                  <strong>Pending pairing</strong>
                  <span>Run the generated bootstrap command on the target host. The worker will appear healthy after registration and heartbeat succeed.</span>
                </div>
              ) : null}

              {cpuFallbackActive ? (
                <div className="info-strip info-strip-warning" role="note">
                  <strong>CPU fallback in effect</strong>
                  <span>
                    {detail.display_name} prefers {formatBackendLabel(detail.preferred_backend)}, but the current job is using CPU because the configured hardware path is not usable right now.
                  </span>
                </div>
              ) : null}

              <section className="worker-detail-metric-grid">
                <WorkerDetailMetric
                  label="Health summary"
                  value={(detailStatusRollup ?? buildWorkerStatusRollup(detail, localWorkerStatus)).compactMessage}
                />
                <WorkerDetailMetric
                  label="Current activity"
                  value={detail.current_stage ?? detail.runtime_summary?.current_stage ?? detail.current_job_id ?? "Idle"}
                />
                <WorkerDetailMetric label="Current backend" value={formatBackendLabel(detailCurrentBackend)} />
                <WorkerDetailMetric label="Concurrency" value={formatConcurrencyLabel(detail)} />
                <WorkerDetailMetric label="Pending assignments" value={String(detail.pending_assignment_count)} />
                <WorkerDetailMetric label="Schedule" value={detail.schedule_summary ?? "Any time"} />
              </section>

              <SectionCard title="Health and execution">
                <WorkerDetailInfoGrid
                  items={[
                    { label: "Host", value: detail.host_summary.hostname ?? "Not reported" },
                    { label: "Preferred backend", value: formatBackendLabel(detail.preferred_backend) },
                    { label: "Actual backend", value: formatBackendLabel(detailCurrentBackend) },
                    { label: "CPU fallback", value: detail.allow_cpu_fallback ? "Allowed" : "Disabled" },
                    { label: "Platform", value: detail.host_summary.platform ?? detail.onboarding_platform ?? "Not reported" },
                    { label: "Current job", value: detail.current_job_id ?? detail.runtime_summary?.current_job_id ?? "Idle" },
                    {
                      label: "Progress",
                      value: formatWorkerProgress(detail.current_progress_percent ?? detail.runtime_summary?.current_progress_percent, detail.current_stage ?? detail.runtime_summary?.current_stage),
                    },
                    { label: "Last seen", value: formatDateTime(detail.last_seen_at) },
                    { label: "Last heartbeat", value: formatDateTime(detail.last_heartbeat_at) },
                  ]}
                />
              </SectionCard>

              <div className="worker-detail-mid-grid">
                {detail.worker_type === "local" ? (
                  <SectionCard title="Local backend diagnostics" subtitle="Runtime truth for the current host worker.">
                    <div className="card-stack">
                      <WorkerDetailDenseGrid
                        compact
                        items={[
                          {
                            label: "Dependencies",
                            value: (
                              <span className="worker-inline-status-list">
                                <WorkerStatusIndicator label="FFmpeg" status={localWorkerStatus?.ffmpeg.status} />
                                <WorkerStatusIndicator label="FFprobe" status={localWorkerStatus?.ffprobe.status} />
                              </span>
                            ),
                            span: "full",
                          },
                          { label: "Eligibility", value: localWorkerStatus?.eligibility_summary ?? "Not reported" },
                          {
                            label: "Configured backend health",
                            value: configuredBackendProbe ? (
                              <WorkerStatusIndicator
                                label={formatBackendLabel(detail.preferred_backend)}
                                status={configuredBackendProbe.status}
                              />
                            ) : "No probe available",
                          },
                        ]}
                      />
                      {selectedHardwareBackendProbe ? (
                        <CapabilityStrip
                          title="Selected backend diagnostic"
                          description={formatSelectedBackendDiagnosticMessage(
                            formatBackendLabel(detail.preferred_backend),
                            selectedHardwareBackendProbe.status,
                            selectedHardwareBackendProbe.reason_unavailable ?? selectedHardwareBackendProbe.message,
                          )}
                          tone={selectedHardwareBackendProbe.status === "failed" ? "danger" : "default"}
                          status={selectedHardwareBackendProbe.status}
                        />
                      ) : null}
                      {selectedRuntimeDevices.length > 0 ? (
                        <div className="worker-device-list">
                          {selectedRuntimeDevices.map((device) => (
                            <div key={device.path} className="worker-device-row">
                              <div className="worker-device-row-main">
                                <WorkerStatusIndicator label={device.path} status={device.status} />
                                <p>
                                  {device.vendor_name ?? "Unknown vendor"}{device.vendor_id ? ` • ${device.vendor_id}` : ""}
                                </p>
                                <p>{device.message}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </SectionCard>
                ) : (
                  <SectionCard title="Worker capability summary" subtitle="What the worker has actually reported.">
                    <WorkerDetailDenseGrid
                      items={[
                        {
                          label: "Execution modes",
                          value: detail.capability_summary.execution_modes.length > 0
                            ? detail.capability_summary.execution_modes.join(" • ")
                            : "Not reported",
                        },
                        {
                          label: "Selected hardware",
                          value: formatSelectedHardwareHint(detail.capability_summary.hardware_hints, detail.preferred_backend),
                        },
                        {
                          label: "Recommended concurrency",
                          value: detail.capability_summary.recommended_concurrency != null
                            ? `${detail.capability_summary.recommended_concurrency} • ${detail.capability_summary.recommended_concurrency_reason ?? "Worker reported recommendation"}`
                            : "Not reported",
                          span: "full",
                        },
                      ]}
                    />
                  </SectionCard>
                )}

                <SectionCard title="Storage and path access" className="worker-storage-card">
                  <WorkerDetailDenseGrid
                    items={[
                      {
                        label: "Scratch",
                        value: (
                          <WorkerPathStatus
                            path={detail.scratch_path ?? detail.runtime_summary?.scratch_dir ?? readScratchPath(detail.runtime_summary?.scratch_status) ?? "Not configured"}
                            status={readStatusValue(detail.runtime_summary?.scratch_status)}
                          />
                        ),
                      },
                      {
                        label: "Path mappings",
                        value: detailPathMappings.length > 0 ? `${detailPathMappings.length} configured` : "Not configured",
                      },
                    ]}
                  >
                    {detailPathMappings.length > 0 ? (
                      <div className="worker-device-list worker-detail-grid-span">
                        {detailPathMappings.map((mapping) => (
                          <div key={`${mapping.server_path}:${mapping.worker_path}`} className="worker-device-row">
                            <div className="worker-device-row-main">
                              <strong>{mapping.label ?? mapping.server_path}</strong>
                              <p>{mapping.server_path} → {mapping.worker_path}</p>
                              <p>{mapping.validation_message ?? "Validation not reported."}</p>
                            </div>
                            {isAttentionStatus(mapping.validation_status) ? (
                              <StatusBadge value={mapping.validation_status ?? "unknown"} />
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="info-strip worker-detail-grid-span worker-storage-banner" role="note">
                        <strong>Direct shared path mode</strong>
                        <span>No explicit mappings are configured. This worker will rely on the same visible media paths unless you add mappings.</span>
                      </div>
                    )}
                  </WorkerDetailDenseGrid>
                </SectionCard>
              </div>

              {(detail.runtime_summary?.telemetry ?? localWorkerStatus?.telemetry) ? (
                <SectionCard title="Current telemetry">
                  <TelemetrySummary telemetry={(detail.runtime_summary?.telemetry ?? localWorkerStatus?.telemetry) as Record<string, unknown>} />
                </SectionCard>
              ) : null}

              {detailRecentJobs.length > 0 ? (
                <SectionCard title="Recent jobs">
                  <div className="list-stack">
                    {detailRecentJobs.map((job) => (
                      <div key={job.job_id} className="list-row">
                        <div>
                          <strong>{job.source_filename ?? job.job_id}</strong>
                          <p>{formatBackendLabel(job.actual_execution_backend ?? job.requested_execution_backend)}</p>
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

              <CollapsibleSection title="Advanced metadata" subtitle="Host and worker metadata for debugging.">
                <KeyValueList
                  items={[
                    { label: "Worker source", value: detail.source },
                    { label: "Registration state", value: detail.registration_status },
                    { label: "Agent version", value: detail.host_summary.agent_version ?? "Not reported" },
                    { label: "Python version", value: detail.host_summary.python_version ?? "Not reported" },
                    {
                      label: "Assigned job ids",
                      value: detail.assigned_job_ids.length > 0 ? detail.assigned_job_ids.join(" • ") : "None",
                    },
                    { label: "Recent failure", value: detail.recent_failure_message ?? "None" },
                    { label: "Pairing expires", value: formatDateTime(detail.pairing_expires_at) },
                  ]}
                />
              </CollapsibleSection>
            </div>
          </section>
        </div>
      ) : null}

      {isAddWorkerOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Add worker">
          <section className="modal-panel modal-panel-wide">
            <div className="section-card-header">
              <div>
                <h2>Add worker</h2>
                <p>Choose whether this Encodr host should become a worker, or generate a bootstrap command for a remote execution node.</p>
              </div>
              <div className="section-card-actions">
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => {
                    setIsAddWorkerOpen(false);
                    setOnboardingResult(null);
                    setAddWorkerMode("choose");
                  }}
                >
                  Close
                </button>
              </div>
            </div>

            {addWorkerMode === "choose" ? (
              <div className="card-stack">
                <button className="button button-primary" type="button" onClick={() => setAddWorkerMode("local")}>
                  Add this host as worker
                </button>
                <button className="button button-secondary" type="button" onClick={() => setAddWorkerMode("remote")}>
                  Add remote worker
                </button>
              </div>
            ) : null}

            {addWorkerMode === "local" ? (
              <div className="card-stack">
                <div className="worker-local-callout" role="note">
                  <strong>Same host runtime</strong>
                  <span>The local worker runs inside the same Encodr stack and uses the current runtime mounts and scratch path.</span>
                </div>
                <WorkerPreferenceFields
                  draft={localDraft}
                  onChange={(next) => setLocalDraft(next as WorkerPreferencePayload)}
                  recommendedConcurrency={recommendedLocalConcurrency(workerStatus)}
                  recommendationReason="Recommended from the detected local runtime capabilities."
                  showPathMappings={false}
                />
                {localDraft.preferred_backend !== "cpu_only" ? (
                  <CapabilityStrip
                    title="Selected local backend"
                    description={`${formatBackendLabel(localDraft.preferred_backend)} is selected as the primary backend for this worker.`}
                    items={localCapabilities.map((item) => ({
                      label: formatBackendLabel(item.backend),
                      status: item.usable ? "healthy" : "degraded",
                      message: item.message,
                    }))}
                  />
                ) : null}
                <div className="section-card-actions worker-modal-actions">
                  <button className="button button-secondary button-small" type="button" onClick={() => setAddWorkerMode("choose")}>
                    Back
                  </button>
                  <button
                    className="button button-primary button-small"
                    type="button"
                    onClick={() => {
                      setupLocalWorkerMutation.mutate(normaliseWorkerDraft(localDraft), {
                        onSuccess: () => {
                          setIsAddWorkerOpen(false);
                          setAddWorkerMode("choose");
                        },
                      });
                    }}
                    disabled={setupLocalWorkerMutation.isPending}
                  >
                    {setupLocalWorkerMutation.isPending ? "Saving…" : "Add this host as worker"}
                  </button>
                </div>
              </div>
            ) : null}

            {addWorkerMode === "remote" ? (
              <div className="card-stack">
                <WorkerPreferenceFields
                  draft={remoteDraft}
                  onChange={(next) => setRemoteDraft(next as RemoteWorkerOnboardingPayload)}
                  recommendedConcurrency={remoteDraft.max_concurrent_jobs ?? 1}
                  recommendationReason="You can refine this after pairing once the worker reports its real capabilities."
                  showPlatform
                  showPathMappings
                />
                <div className="section-card-actions worker-modal-actions">
                  <button className="button button-secondary button-small" type="button" onClick={() => setAddWorkerMode("choose")}>
                    Back
                  </button>
                  <button
                    className="button button-primary button-small"
                    type="button"
                    onClick={() => {
                      createRemoteWorkerMutation.mutate(normaliseRemoteDraft(remoteDraft), {
                        onSuccess: (result) => setOnboardingResult(result),
                      });
                    }}
                    disabled={createRemoteWorkerMutation.isPending}
                  >
                    {createRemoteWorkerMutation.isPending ? "Generating…" : "Generate bootstrap command"}
                  </button>
                </div>

                {onboardingResult ? (
                  <BootstrapResultPanel result={onboardingResult} />
                ) : null}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {editingWorker && editDraft ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Edit worker">
          <section className="modal-panel modal-panel-wide worker-edit-modal">
            <div className="section-card-header">
              <div>
                <h2>Edit worker</h2>
                <p>{editingWorker.display_name}</p>
              </div>
              <div className="section-card-actions">
                <button className="button button-secondary button-small" type="button" onClick={() => setEditingWorker(null)}>
                  Close
                </button>
              </div>
            </div>

            <WorkerPreferenceFields
              draft={editDraft}
              onChange={(next) => setEditDraft(next as WorkerPreferencePayload)}
              recommendedConcurrency={editingWorker.capability_summary.recommended_concurrency ?? editingWorker.max_concurrent_jobs ?? 1}
              recommendationReason={editingWorker.capability_summary.recommended_concurrency_reason ?? "Recommended from the worker capability report."}
              showPathMappings={editingWorker.worker_type === "remote"}
            />

            {editingWorker.worker_type === "remote" ? (
              <div className="info-strip" role="note">
                <strong>Remote uninstall</strong>
                <span>Deleting this worker revokes it server-side and then shows the standalone uninstall command for the target host.</span>
              </div>
            ) : null}

            <div className="section-card-actions worker-modal-actions">
              <button
                className="button button-primary button-small"
                type="button"
                onClick={() => {
                  updateWorkerPreferencesMutation.mutate(
                    { workerId: editingWorker.id, payload: normaliseWorkerDraft(editDraft) },
                    {
                      onSuccess: () => setEditingWorker(null),
                    },
                  );
                }}
                disabled={updateWorkerPreferencesMutation.isPending}
              >
                {updateWorkerPreferencesMutation.isPending ? "Saving…" : "Save worker"}
              </button>
              <button
                className="button button-danger button-small"
                type="button"
                onClick={() => {
                  deleteWorkerMutation.mutate(editingWorker.id, {
                    onSuccess: (result) => {
                      setRemovalResult(result);
                      setEditingWorker(null);
                    },
                  });
                }}
                disabled={deleteWorkerMutation.isPending}
              >
                {deleteWorkerMutation.isPending ? "Removing…" : "Delete worker"}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {removalResult ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Worker uninstall command">
          <section className="modal-panel">
            <div className="section-card-header">
              <div>
                <h2>Worker removed</h2>
                <p>{removalResult.worker_key} was removed from Encodr. Run this on the remote host to uninstall the agent.</p>
              </div>
              <div className="section-card-actions">
                <button className="button button-secondary button-small" type="button" onClick={() => setRemovalResult(null)}>
                  Close
                </button>
              </div>
            </div>
            <label className="field">
              <span>Standalone uninstall command</span>
              <textarea readOnly value={removalResult.uninstall_command} rows={5} />
            </label>
            <div className="list-stack">
              {removalResult.notes.map((note) => (
                <div key={note} className="info-strip" role="note">
                  <span>{note}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function WorkerPreferenceFields({
  draft,
  onChange,
  recommendedConcurrency,
  recommendationReason,
  showPlatform = false,
  showPathMappings = false,
}: {
  draft: WorkerPreferencePayload | RemoteWorkerOnboardingPayload;
  onChange: (next: WorkerPreferencePayload | RemoteWorkerOnboardingPayload) => void;
  recommendedConcurrency: number;
  recommendationReason: string;
  showPlatform?: boolean;
  showPathMappings?: boolean;
}) {
  const mappings = draft.path_mappings ?? [];

  return (
    <div className="worker-preference-form">
      <div className="worker-preference-column">
        <label className="field">
          <span>Worker label</span>
          <input
            aria-label="Worker label"
            value={draft.display_name ?? ""}
            onChange={(event) => onChange({ ...draft, display_name: event.target.value })}
          />
        </label>
        <label className="field">
          <span>Preferred backend</span>
          <select
            aria-label="Worker preferred backend"
            value={draft.preferred_backend}
            onChange={(event) => onChange({ ...draft, preferred_backend: event.target.value })}
          >
            {BACKEND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Scratch path</span>
          <input
            aria-label="Worker scratch path"
            value={draft.scratch_path ?? ""}
            onChange={(event) => onChange({ ...draft, scratch_path: event.target.value })}
          />
        </label>
      </div>

      <div className="worker-preference-column">
        <label className="field">
          <span>Concurrency</span>
          <input
            aria-label="Worker concurrency"
            type="number"
            min={1}
            max={8}
            value={draft.max_concurrent_jobs ?? recommendedConcurrency}
            onChange={(event) => onChange({ ...draft, max_concurrent_jobs: Number(event.target.value) || 1 })}
          />
          <span className="worker-field-helper">
            Recommendation: {recommendedConcurrency} concurrent job{recommendedConcurrency === 1 ? "" : "s"} • {recommendationReason}
          </span>
        </label>

        <label className="worker-checkbox-row">
          <input
            aria-label="Worker CPU fallback"
            type="checkbox"
            checked={draft.allow_cpu_fallback}
            onChange={(event) => onChange({ ...draft, allow_cpu_fallback: event.target.checked })}
          />
          <span>Allow CPU fallback</span>
        </label>

        {showPlatform && "platform" in draft ? (
          <label className="field">
            <span>Platform</span>
            <select
              aria-label="Worker platform"
              value={draft.platform}
              onChange={(event) => onChange({ ...draft, platform: event.target.value as "windows" | "linux" | "macos" })}
            >
              {PLATFORM_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      <div className="worker-preference-full">
        <ScheduleWindowsEditor
          label="Schedule windows"
          value={draft.schedule_windows ?? []}
          onChange={(value) => onChange({ ...draft, schedule_windows: value })}
          concurrencyValue={draft.max_concurrent_jobs ?? recommendedConcurrency}
          onConcurrencyChange={(value) => onChange({ ...draft, max_concurrent_jobs: Math.max(1, Math.min(8, value)) })}
        />
      </div>

      {showPathMappings ? (
        <div className="field worker-preference-full">
          <span>Path mappings</span>
          <PathMappingsEditor
            mappings={mappings}
            onChange={(nextMappings) => onChange({ ...draft, path_mappings: nextMappings })}
          />
        </div>
      ) : null}
    </div>
  );
}

function WorkerInventoryStat({
  label,
  value,
  clamp = false,
}: {
  label: string;
  value: ReactNode;
  clamp?: boolean;
}) {
  return (
    <div className="worker-stat">
      <span>{label}</span>
      <div className={`worker-stat-value${clamp ? " worker-stat-clamped" : ""}`}>{value}</div>
    </div>
  );
}

function WorkerDetailMetric({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="worker-detail-metric">
      <span>{label}</span>
      <div className="worker-detail-metric-value">{value}</div>
    </div>
  );
}

function WorkerDetailTag({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="worker-detail-tag">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function WorkerStatusRollupView({ rollup, compact = false }: { rollup: WorkerStatusRollupResult; compact?: boolean }) {
  return (
    <div className="worker-status-rollup">
      <StatusBadge value={rollup.badge} />
      <span className="worker-status-rollup-message">{compact ? rollup.compactMessage : rollup.message}</span>
    </div>
  );
}

function WorkerStatusIndicator({
  label,
  status,
}: {
  label: string;
  status: string | null | undefined;
}) {
  const resolvedStatus = status ?? "unknown";
  return (
    <span className="worker-status-indicator">
      <span className={`worker-status-dot worker-status-dot-${statusDotTone(resolvedStatus)}`} aria-hidden="true" />
      <span>{label}</span>
      {isAttentionStatus(resolvedStatus) ? <StatusBadge value={resolvedStatus} /> : null}
    </span>
  );
}

function WorkerPathStatus({
  path,
  status,
}: {
  path: string;
  status: string | null | undefined;
}) {
  return (
    <span className="worker-path-status">
      <WorkerStatusIndicator label={path} status={status} />
    </span>
  );
}

function WorkerDetailInfoGrid({
  items,
}: {
  items: Array<{ label: string; value: ReactNode }>;
}) {
  return (
    <div className="worker-detail-info-grid">
      {items.map((item) => (
        <div key={item.label} className="worker-detail-info-item">
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}

function WorkerDetailDenseGrid({
  items,
  children,
  compact = false,
}: {
  items: Array<{ label: string; value: ReactNode; span?: "full" }>;
  children?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`worker-detail-dense-grid${compact ? " worker-detail-dense-grid-compact" : ""}`}>
      {items.map((item) => (
        <div
          key={item.label}
          className={`worker-detail-dense-item${item.span === "full" ? " worker-detail-grid-span" : ""}`}
        >
          <span>{item.label}</span>
          <div className="worker-detail-dense-value">{item.value}</div>
        </div>
      ))}
      {children}
    </div>
  );
}

function PathMappingsEditor({
  mappings,
  onChange,
}: {
  mappings: PathMappingDraft[];
  onChange: (next: PathMappingDraft[]) => void;
}) {
  return (
    <div className="card-stack">
      {mappings.length === 0 ? (
        <div className="info-strip" role="note">
          <strong>Optional</strong>
          <span>Add explicit server-to-worker path mappings when the remote worker sees shared storage at a different path.</span>
        </div>
      ) : null}
      {mappings.map((mapping, index) => (
        <div key={`${mapping.server_path}-${mapping.worker_path}-${index}`} className="settings-rules-fields settings-rules-fields-compact">
          <label className="field">
            <span>Label</span>
            <input
              aria-label={`Path mapping label ${index + 1}`}
              value={mapping.label ?? ""}
              onChange={(event) => {
                const next = [...mappings];
                next[index] = { ...mapping, label: event.target.value };
                onChange(next);
              }}
            />
          </label>
          <label className="field">
            <span>Server path</span>
            <input
              aria-label={`Path mapping server path ${index + 1}`}
              value={mapping.server_path}
              onChange={(event) => {
                const next = [...mappings];
                next[index] = { ...mapping, server_path: event.target.value };
                onChange(next);
              }}
            />
          </label>
          <label className="field">
            <span>Worker path</span>
            <input
              aria-label={`Path mapping worker path ${index + 1}`}
              value={mapping.worker_path}
              onChange={(event) => {
                const next = [...mappings];
                next[index] = { ...mapping, worker_path: event.target.value };
                onChange(next);
              }}
            />
          </label>
          <div className="section-card-actions">
            <button
              className="button button-secondary button-small"
              type="button"
              onClick={() => onChange(mappings.filter((_, itemIndex) => itemIndex !== index))}
            >
              Remove mapping
            </button>
          </div>
        </div>
      ))}
      <div className="section-card-actions">
        <button
          className="button button-secondary button-small"
          type="button"
          onClick={() => onChange([...mappings, { ...EMPTY_PATH_MAPPING }])}
        >
          Add mapping
        </button>
      </div>
    </div>
  );
}

function CapabilityStrip({
  title,
  description = "Backend diagnostics are scoped to the worker's selected primary backend.",
  tone = "default",
  status,
  items = [],
}: {
  title: string;
  description?: string;
  tone?: "default" | "danger";
  status?: string;
  items?: Array<{ label: string; status: string; message: string }>;
}) {
  if (items.length === 0) {
    return (
      <div className={`capability-strip capability-strip-${tone}`} role="note">
        <strong>{title}</strong>
        <span>No diagnostic payload is available for the selected backend yet.</span>
      </div>
    );
  }

  return (
    <div className={`capability-strip capability-strip-${tone}`}>
      <div className="capability-strip-copy">
        <div className="capability-strip-heading">
          <strong>{title}</strong>
          {status ? <StatusBadge value={status} /> : null}
        </div>
        <p>{description}</p>
      </div>
    </div>
  );
}

function BootstrapResultPanel({ result }: { result: RemoteWorkerOnboardingResponse }) {
  return (
    <div className="card-stack">
      <div className="info-strip">
        <strong>{result.worker.display_name}</strong>
        <span>Pending pairing until {formatDateTime(result.pairing_token_expires_at)}</span>
      </div>
      <label className="field">
        <span>Bootstrap command</span>
        <textarea readOnly value={result.bootstrap_command} rows={7} />
      </label>
      <label className="field">
        <span>Standalone uninstall command</span>
        <textarea readOnly value={result.uninstall_command} rows={5} />
      </label>
      <div className="list-stack">
        {result.notes.map((note) => (
          <div key={note} className="info-strip" role="note">
            <span>{note}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TelemetrySummary({ telemetry }: { telemetry: Record<string, unknown> }) {
  const gpu = telemetry.gpu as Record<string, unknown> | null | undefined;
  return (
    <div className="worker-telemetry-grid">
      <TelemetryMetric label="CPU" value={formatPercentValue(telemetry.cpu_usage_percent)} />
      <TelemetryMetric label="Process CPU" value={formatPercentValue(telemetry.process_cpu_usage_percent)} />
      <TelemetryMetric label="Memory" value={formatPercentValue(telemetry.memory_usage_percent)} />
      <TelemetryMetric label="Process memory" value={formatBytes(readNumber(telemetry.process_memory_bytes))} />
      <TelemetryMetric label="CPU temp" value={formatTemperature(telemetry.cpu_temperature_c)} />
      <TelemetryMetric label="GPU" value={formatGpuMetric(gpu)} />
    </div>
  );
}

function TelemetryMetric({ label, value }: { label: string; value: string }) {
  const unavailable = isUnavailableMetric(value);

  return (
    <div className="worker-telemetry-item">
      <span>{label}</span>
      <strong className={unavailable ? "worker-telemetry-unavailable" : undefined}>
        {unavailable ? "—" : value}
      </strong>
    </div>
  );
}

function recommendedLocalConcurrency(workerStatus: WorkerStatus) {
  const recommended = workerStatus.hardware_probes.find((item) => item.backend === "cpu")?.details?.recommended_concurrency;
  return typeof recommended === "number" && Number.isFinite(recommended) ? recommended : 1;
}

function readScratchPath(payload: Record<string, unknown> | null | undefined) {
  const path = payload?.path;
  return typeof path === "string" ? path : null;
}

function readStatusValue(payload: Record<string, unknown> | null | undefined) {
  const status = payload?.status;
  return typeof status === "string" ? status : null;
}

function normaliseWorkerDraft(draft: WorkerPreferencePayload): WorkerPreferencePayload {
  return {
    ...draft,
    display_name: draft.display_name?.trim() || undefined,
    max_concurrent_jobs: Math.max(1, Math.min(8, Number(draft.max_concurrent_jobs ?? 1) || 1)),
    scratch_path: draft.scratch_path?.trim() || undefined,
    path_mappings: (draft.path_mappings ?? [])
      .map((mapping) => ({
        label: mapping.label?.trim() || undefined,
        server_path: mapping.server_path.trim(),
        worker_path: mapping.worker_path.trim(),
      }))
      .filter((mapping) => mapping.server_path && mapping.worker_path),
  };
}

function normaliseRemoteDraft(draft: RemoteWorkerOnboardingPayload): RemoteWorkerOnboardingPayload {
  return {
    ...normaliseWorkerDraft(draft),
    platform: draft.platform,
  };
}

function formatConcurrencyLabel(worker: {
  max_concurrent_jobs: number | null;
  capability_summary?: { recommended_concurrency?: number | null } | null;
}) {
  if (worker.max_concurrent_jobs == null) {
    return "Not configured";
  }
  const recommended = worker.capability_summary?.recommended_concurrency;
  if (recommended != null && recommended !== worker.max_concurrent_jobs) {
    return `${worker.max_concurrent_jobs} (recommended ${recommended})`;
  }
  return `${worker.max_concurrent_jobs}`;
}

function isAttentionStatus(status: string | null | undefined) {
  const normalized = (status ?? "unknown").toLowerCase();
  return !["healthy", "ok", "running", "available", "enabled", "valid", "passed", "succeeded"].includes(normalized);
}

function statusDotTone(status: string | null | undefined) {
  const normalized = (status ?? "unknown").toLowerCase();
  if (["failed", "error", "missing", "unavailable", "invalid"].includes(normalized)) {
    return "danger";
  }
  if (isAttentionStatus(normalized)) {
    return "warning";
  }
  return "healthy";
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

function formatSelectedBackendDiagnosticMessage(backendLabel: string, status: string, reason: string | null | undefined) {
  const reasonText = reason ? trimSentencePunctuation(reason) : "No specific issue reported";
  if (status === "failed") {
    return `${backendLabel} is selected as the primary backend, but failed to initialize. Reason: ${reasonText}.`;
  }
  return `${backendLabel} is selected as the primary backend. Reason: ${reasonText}.`;
}

function isUnavailableMetric(value: string) {
  const normalized = value.trim().toLowerCase();
  return normalized === "unavailable" || normalized === "not available";
}

function readNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function buildWorkerStatusRollup(
  worker: Pick<WorkerInventorySummary, "worker_type" | "preferred_backend" | "allow_cpu_fallback" | "health_status" | "health_summary">,
  localWorkerStatus: WorkerStatus | null,
): WorkerStatusRollupResult {
  const configuredBackendProbe = worker.worker_type === "local"
    ? localWorkerStatus?.hardware_probes.find((item) => item.preference_key === worker.preferred_backend)
    : null;

  if (configuredBackendProbe) {
    const backendHealth = configuredBackendProbe.status.toLowerCase();
    const backendReason = configuredBackendProbe.reason_unavailable ?? configuredBackendProbe.message;
    const attentionReason = backendReason ? trimSentencePunctuation(backendReason) : null;

    if (backendHealth === "healthy") {
      return {
        badge: "healthy",
        message: "The local worker is healthy and available.",
        compactMessage: "Available",
        attentionMessage: null,
      };
    }

    if (backendHealth === "failed" || !configuredBackendProbe.usable_by_ffmpeg) {
      if (worker.allow_cpu_fallback) {
        return {
          badge: "degraded",
          message: `Primary backend failed. Falling back to CPU execution.${backendReason ? ` Reason: ${backendReason}` : ""}`,
          compactMessage: "CPU fallback active",
          attentionMessage: attentionReason
            ? `Primary backend failed (Reason: ${attentionReason}). Worker is safely falling back to CPU execution.`
            : "Primary backend failed. Worker is safely falling back to CPU execution.",
        };
      }

      return {
        badge: "failed",
        message: "Primary backend failed and CPU fallback is disabled. Worker cannot execute jobs.",
        compactMessage: "Cannot execute jobs",
        attentionMessage: attentionReason
          ? `Primary backend failed (Reason: ${attentionReason}). CPU fallback is disabled. Worker cannot execute jobs.`
          : "Primary backend failed. CPU fallback is disabled. Worker cannot execute jobs.",
      };
    }
  }

  return {
    badge: worker.health_status ?? "unknown",
    message: worker.health_summary ?? "No health summary reported.",
    compactMessage: worker.health_summary ?? "No summary reported",
    attentionMessage: null,
  };
}

function trimSentencePunctuation(value: string) {
  return value.trim().replace(/[.!?]+$/, "");
}

function buildWorkerPrimaryIssues(detail: WorkerInventoryDetail, localWorkerStatus: WorkerStatus | null) {
  const issues = new Set<string>();
  if (detail.health_status !== "healthy" && detail.health_summary) {
    issues.add(detail.health_summary);
  }
  if (detail.worker_state === "remote_pending_pairing") {
    issues.add("This worker has not paired yet.");
  }
  if (localWorkerStatus) {
    if (!localWorkerStatus.eligible) {
      issues.add(localWorkerStatus.eligibility_summary);
    }
    const preferredProbe = localWorkerStatus.hardware_probes.find(
      (item) => item.preference_key === detail.preferred_backend,
    );
    if (preferredProbe && !preferredProbe.usable_by_ffmpeg) {
      issues.add(preferredProbe.reason_unavailable ?? preferredProbe.message);
    }
  }
  return [...issues];
}

function formatWorkerProgress(progressPercent: number | null | undefined, stage: string | null | undefined) {
  if (typeof progressPercent === "number") {
    return `${progressPercent}%`;
  }
  if (stage) {
    return titleCase(stage.replace(/_/g, " "));
  }
  return "Idle";
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
  }[value] ?? titleCase(value.replace(/_/g, " "));
}

function formatSelectedHardwareHint(hardwareHints: string[], preferredBackend: string | null | undefined) {
  if (!preferredBackend || preferredBackend === "cpu_only" || preferredBackend === "cpu") {
    return "CPU selected";
  }
  const selectedBackend = backendKeyForPreference(preferredBackend);
  if (!selectedBackend) {
    return formatBackendLabel(preferredBackend);
  }
  return hardwareHints.includes(selectedBackend)
    ? formatBackendLabel(selectedBackend)
    : `${formatBackendLabel(preferredBackend)} not reported`;
}

function backendKeyForPreference(value: string) {
  switch (value) {
    case "prefer_intel_igpu":
      return "intel_igpu";
    case "prefer_nvidia_gpu":
      return "nvidia_gpu";
    case "prefer_amd_gpu":
      return "amd_gpu";
    default:
      return undefined;
  }
}
