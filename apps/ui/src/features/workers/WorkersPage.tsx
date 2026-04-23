import { useEffect, useMemo, useState } from "react";
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
  WorkerInventoryDetail,
  WorkerPreferencePayload,
  WorkerRemovalResponse,
  WorkerStatus,
} from "../../lib/types/api";
import {
  formatBytes,
  formatDateTime,
  formatDurationSeconds,
  formatRelativeBoolean,
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
        .map((item) => ({
          backend: item.backend,
          usable: item.usable_by_ffmpeg,
          message: item.message,
        })),
    [workerStatus?.hardware_probes],
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

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Workers"
        title="Workers"
        description="Add execution nodes, pair remote agents, and manage backend, concurrency, schedule, and storage access per worker."
        actions={(
          <button
            className="button button-primary"
            type="button"
            onClick={() => {
              setIsAddWorkerOpen(true);
              setAddWorkerMode("choose");
              setOnboardingResult(null);
            }}
          >
            Add worker
          </button>
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
      {deleteWorkerMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to remove worker" message={deleteWorkerMutation.error.message} />
      ) : null}

      <section className={`jobs-review-layout${detail ? "" : " jobs-review-layout-single"}`}>
        <SectionCard
          title="Worker inventory"
          subtitle={noWorkersConfigured ? "No workers configured yet." : `${workers.length} worker${workers.length === 1 ? "" : "s"} configured`}
        >
          {noWorkersConfigured ? (
            <EmptyState
              title="No workers configured"
              message="Add this host as a worker or pair a remote worker when you are ready to give Encodr execution capacity."
            />
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
                        <StatusBadge value={item.health_status} />
                      </div>
                    </div>
                    <div className="record-list-meta">
                      <span className="record-list-kicker">{item.worker_type === "local" ? "This host" : "Remote worker"}</span>
                      <span>{formatBackendLabel(item.preferred_backend)}</span>
                      <span>{formatConcurrencyLabel(item)}</span>
                      <span>{item.schedule_summary ?? "Any time"}</span>
                      <span className="record-list-emphasis">{item.health_summary ?? "No health summary reported."}</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </SectionCard>

        {detail ? (
          <SectionCard
            title="Worker detail"
            subtitle={detail.display_name}
            actions={(
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
              </div>
            )}
          >
            <div className="card-stack">
              {detail.worker_state === "remote_pending_pairing" ? (
                <div className="info-strip info-strip-warning" role="note">
                  <strong>Pending pairing</strong>
                  <span>Run the generated bootstrap command on the target host. The worker will appear healthy after registration and heartbeat succeed.</span>
                </div>
              ) : null}

              <KeyValueList
                items={[
                  { label: "Worker key", value: detail.worker_key },
                  { label: "Type", value: <StatusBadge value={detail.worker_type} /> },
                  { label: "State", value: <StatusBadge value={detail.worker_state} /> },
                  { label: "Health", value: <StatusBadge value={detail.health_status} /> },
                  { label: "Enabled", value: formatRelativeBoolean(detail.enabled) },
                  { label: "Preferred backend", value: formatBackendLabel(detail.preferred_backend) },
                  { label: "CPU fallback", value: detail.allow_cpu_fallback ? "Allowed" : "Disabled" },
                  { label: "Concurrency", value: formatConcurrencyLabel(detail) },
                  { label: "Schedule", value: detail.schedule_summary ?? "Any time" },
                  { label: "Scratch path", value: detail.scratch_path ?? detail.runtime_summary?.scratch_dir ?? "Not configured" },
                  { label: "Platform", value: detail.host_summary.platform ?? detail.onboarding_platform ?? "Not reported" },
                  { label: "Host", value: detail.host_summary.hostname ?? "Not reported" },
                  { label: "Last heartbeat", value: formatDateTime(detail.last_heartbeat_at) },
                  { label: "Last seen", value: formatDateTime(detail.last_seen_at) },
                ]}
              />

              <div className="metric-grid metric-grid-compact">
                <div className="metric-panel">
                  <span className="metric-label">Pending assignments</span>
                  <strong>{detail.pending_assignment_count}</strong>
                </div>
                <div className="metric-panel">
                  <span className="metric-label">Current job</span>
                  <strong>{detail.current_job_id ?? detail.runtime_summary?.current_job_id ?? "Idle"}</strong>
                </div>
                <div className="metric-panel">
                  <span className="metric-label">Current backend</span>
                  <strong>{formatBackendLabel(detail.current_backend ?? detail.runtime_summary?.current_backend)}</strong>
                </div>
                <div className="metric-panel">
                  <span className="metric-label">Progress</span>
                  <strong>
                    {detail.current_progress_percent ?? detail.runtime_summary?.current_progress_percent ?? detail.current_stage ?? detail.runtime_summary?.current_stage ?? "Idle"}
                    {typeof (detail.current_progress_percent ?? detail.runtime_summary?.current_progress_percent) === "number" ? "%" : ""}
                  </strong>
                </div>
              </div>

              {detail.runtime_summary?.telemetry ? (
                <SectionCard title="Current telemetry">
                  <TelemetrySummary telemetry={detail.runtime_summary.telemetry} />
                </SectionCard>
              ) : null}

              <SectionCard title="Storage access">
                <div className="card-stack">
                  <KeyValueList
                    items={[
                      {
                        label: "Scratch validation",
                        value: formatScratchStatus(detail.runtime_summary?.scratch_status),
                      },
                      {
                        label: "Path mappings",
                        value: detailPathMappings.length > 0 ? `${detailPathMappings.length} configured` : "Not configured",
                      },
                    ]}
                  />
                  {detailPathMappings.length > 0 ? (
                    <div className="list-stack">
                      {detailPathMappings.map((mapping) => (
                        <div key={`${mapping.server_path}:${mapping.worker_path}`} className="list-row">
                          <div>
                            <strong>{mapping.label ?? mapping.server_path}</strong>
                            <p>{mapping.server_path} → {mapping.worker_path}</p>
                            <p>{mapping.validation_message ?? "Validation not reported."}</p>
                          </div>
                          <StatusBadge value={mapping.validation_status ?? "unknown"} />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="info-strip" role="note">
                      <strong>Direct shared path mode</strong>
                      <span>No explicit mappings are configured. This worker will rely on the same visible media paths unless you add mappings.</span>
                    </div>
                  )}
                </div>
              </SectionCard>

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
            </div>
          </SectionCard>
        ) : null}
      </section>

      {isAddWorkerOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Add worker">
          <section className="modal-panel">
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
                <div className="info-strip" role="note">
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
                <CapabilityStrip
                  title="Detected local backends"
                  items={localCapabilities.map((item) => ({
                    label: formatBackendLabel(item.backend),
                    status: item.usable ? "healthy" : "degraded",
                    message: item.message,
                  }))}
                />
                <div className="section-card-actions">
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
                <div className="section-card-actions">
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
          <section className="modal-panel">
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

            <div className="section-card-actions">
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
              {editingWorker.enabled ? (
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => disableMutation.mutate(editingWorker.id)}
                  disabled={disableMutation.isPending}
                >
                  {disableMutation.isPending ? "Disabling…" : "Disable"}
                </button>
              ) : (
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => enableMutation.mutate(editingWorker.id)}
                  disabled={enableMutation.isPending}
                >
                  {enableMutation.isPending ? "Enabling…" : "Enable"}
                </button>
              )}
              {editingWorker.worker_type === "remote" ? (
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
              ) : null}
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
    <div className="settings-rules-fields settings-rules-fields-compact">
      <label className="field">
        <span>Worker label</span>
        <input
          aria-label="Worker label"
          value={draft.display_name ?? ""}
          onChange={(event) => onChange({ ...draft, display_name: event.target.value })}
        />
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

      <label className="field field-checkbox">
        <span>Allow CPU fallback</span>
        <input
          aria-label="Worker CPU fallback"
          type="checkbox"
          checked={draft.allow_cpu_fallback}
          onChange={(event) => onChange({ ...draft, allow_cpu_fallback: event.target.checked })}
        />
      </label>

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
      </label>

      <div className="info-strip" role="note">
        <strong>Recommendation</strong>
        <span>{recommendedConcurrency} concurrent job{recommendedConcurrency === 1 ? "" : "s"} • {recommendationReason}</span>
      </div>

      <label className="field">
        <span>Scratch path</span>
        <input
          aria-label="Worker scratch path"
          value={draft.scratch_path ?? ""}
          onChange={(event) => onChange({ ...draft, scratch_path: event.target.value })}
        />
      </label>

      <ScheduleWindowsEditor
        label="Schedule windows"
        value={draft.schedule_windows ?? []}
        onChange={(value) => onChange({ ...draft, schedule_windows: value })}
      />

      {showPathMappings ? (
        <div className="field">
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
  items,
}: {
  title: string;
  items: Array<{ label: string; status: string; message: string }>;
}) {
  if (items.length === 0) {
    return (
      <div className="info-strip" role="note">
        <strong>{title}</strong>
        <span>CPU execution is available. No hardware backend is currently usable.</span>
      </div>
    );
  }

  return (
    <div className="card-stack">
      <div className="info-strip">
        <strong>{title}</strong>
        <span>Encodr only offers the backends that the current runtime can actually validate.</span>
      </div>
      <div className="list-stack">
        {items.map((item) => (
          <div key={item.label} className="list-row">
            <div>
              <strong>{item.label}</strong>
              <p>{item.message}</p>
            </div>
            <StatusBadge value={item.status} />
          </div>
        ))}
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

function recommendedLocalConcurrency(workerStatus: WorkerStatus) {
  const recommended = workerStatus.hardware_probes.find((item) => item.backend === "cpu")?.details?.recommended_concurrency;
  return typeof recommended === "number" && Number.isFinite(recommended) ? recommended : 1;
}

function readScratchPath(payload: Record<string, unknown> | null | undefined) {
  const path = payload?.path;
  return typeof path === "string" ? path : null;
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

function formatScratchStatus(status: Record<string, unknown> | null | undefined) {
  if (!status) {
    return "Not reported";
  }
  const path = typeof status.path === "string" ? status.path : null;
  const state = typeof status.status === "string" ? status.status : "unknown";
  return (
    <span className="badge-row">
      <StatusBadge value={state} />
      <span>{path ?? "Unknown path"}</span>
    </span>
  );
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
  }[value] ?? titleCase(value.replace(/_/g, " "));
}
