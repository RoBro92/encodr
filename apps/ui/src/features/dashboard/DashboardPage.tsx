import { Link } from "react-router-dom";

import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useAnalyticsDashboardQuery,
  useJobProgressStream,
  useJobsQuery,
  useRuntimeStatusQuery,
  useStorageStatusQuery,
  useWorkerStatusQuery,
} from "../../lib/api/hooks";
import type { JobSummary, RuntimeStatus, StorageStatus, WorkerStatus } from "../../lib/types/api";
import { formatBytes, titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

type ActionItem = {
  title: string;
  description: string;
  to: string;
};

type SystemNode = {
  name: string;
  detail: string;
  status: string;
  tone: "nominal" | "processing" | "idle" | "degraded" | "offline";
};

export function DashboardPage() {
  useJobProgressStream();
  const analyticsQuery = useAnalyticsDashboardQuery();
  const workerQuery = useWorkerStatusQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();
  const runningJobsQuery = useJobsQuery({ status: "running", limit: 10 });

  const error =
    analyticsQuery.error ??
    workerQuery.error ??
    runtimeQuery.error ??
    storageQuery.error ??
    runningJobsQuery.error;
  const loading =
    analyticsQuery.isLoading ||
    workerQuery.isLoading ||
    runtimeQuery.isLoading ||
    storageQuery.isLoading ||
    runningJobsQuery.isLoading;

  if (loading) {
    return <LoadingBlock label="Loading dashboard" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load the dashboard" message={error.message} />;
  }

  const analytics = analyticsQuery.data;
  const worker = workerQuery.data;
  const runtime = runtimeQuery.data;
  const storage = storageQuery.data;
  const runningJobs = runningJobsQuery.data?.items ?? [];
  const jobStatusCounts = toCountMap(analytics?.overview.jobs_by_status ?? []);
  const completedJobCount = (jobStatusCounts.completed ?? 0) + (jobStatusCounts.skipped ?? 0);
  const manualReviewCount = jobStatusCounts.manual_review ?? 0;
  const failedJobCount = jobStatusCounts.failed ?? 0;
  const interruptedJobCount = jobStatusCounts.interrupted ?? 0;
  const runningJobCount = jobStatusCounts.running ?? 0;
  const totalTranscodes = countByValue(analytics?.overview.plans_by_action ?? [], "transcode");
  const processedFileCount = analytics?.overview.processed_file_count ?? completedJobCount;
  const averageProcessedPerDay = analytics?.overview.average_processed_per_day ?? null;
  const totalSpaceSaved = analytics?.storage.total_space_saved_bytes ?? 0;
  const averageSavedPerDay = analytics?.storage.average_space_saved_per_day_bytes ?? null;
  const totalAudioRemoved = analytics?.media.total_audio_tracks_removed ?? 0;
  const totalSubtitleRemoved = analytics?.media.total_subtitle_tracks_removed ?? 0;
  const actionItems = buildActionItems(runtime, storage, worker);
  const activeJob = pickActiveJob(runningJobs, worker?.current_job_id);
  const activeProgress = clampProgress(activeJob?.progress_percent ?? worker?.current_progress_percent ?? null);
  const systemNodes = buildSystemNodes(runtime, storage, worker);

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Dashboard"
        title="Dashboard"
        description="Library, jobs, review, and storage at a glance."
      />

      {actionItems.length > 0 ? (
        <section className="dashboard-action-banner" role="note" aria-label="Action required">
          <div>
            <span className="section-eyebrow">Action Required</span>
            <h2>Finish critical setup before relying on automation.</h2>
          </div>
          <div className="dashboard-action-list">
            {actionItems.map((item) => (
              <Link key={item.title} className="dashboard-action-item" to={item.to}>
                <strong>{item.title}</strong>
                <span>{item.description}</span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      <section className="dashboard-analytics-row" aria-label="Historical processing metrics">
        <article className="dashboard-metric-card">
          <span className="metric-label">Files Processed</span>
          <strong>{formatInteger(processedFileCount)}</strong>
          <small>{formatAverage(averageProcessedPerDay, "Average per day")}</small>
        </article>
        <article className="dashboard-metric-card">
          <span className="metric-label">Storage Saved</span>
          <strong>{formatBytes(totalSpaceSaved)}</strong>
          <small>{averageSavedPerDay == null ? "Average saved per day unavailable" : `${formatBytes(averageSavedPerDay)} average saved per day`}</small>
        </article>
        <article className="dashboard-metric-card">
          <span className="metric-label">Media Cleaned</span>
          <strong>{formatInteger(totalAudioRemoved)} audio</strong>
          <small>{formatInteger(totalSubtitleRemoved)} subtitles removed</small>
        </article>
      </section>

      <section className="dashboard-command-grid" aria-label="Transcoding command center">
        <article className="dashboard-widget">
          <div className="dashboard-widget-header">
            <div>
              <h2>Transcoding Outcomes</h2>
              <p>Current queue health and outcomes that need attention.</p>
            </div>
            <Link className="text-link" to={APP_ROUTES.jobs}>Open jobs</Link>
          </div>

          <div className="dashboard-outcome-top">
            <div className={`dashboard-outcome-card${manualReviewCount > 0 ? " dashboard-outcome-card-attention" : ""}`}>
              <span className="metric-label">Manual Review</span>
              <strong>{formatInteger(manualReviewCount)}</strong>
            </div>
            <div className="dashboard-outcome-card">
              <span className="metric-label">Total Transcodes</span>
              <strong>{formatInteger(totalTranscodes)}</strong>
            </div>
          </div>

          <div className="dashboard-breakdown-grid">
            <StatusSummaryCard label="Failed" value={failedJobCount} tone="danger" />
            <StatusSummaryCard label="Interrupted" value={interruptedJobCount} tone="warning" />
            <StatusSummaryCard label="Running" value={runningJobCount} tone="success" />
          </div>
        </article>

        <article className="dashboard-widget dashboard-active-file-card">
          <div className="dashboard-widget-header">
            <div>
              <h2>Active Transcoding File</h2>
              <p>{activeJob ? "Current worker output." : "System Idle - Waiting for jobs"}</p>
            </div>
            {activeJob ? <StatusBadge value={activeJob.status} /> : <StatusBadge value="idle" />}
          </div>

          {activeJob ? (
            <div className="dashboard-active-file-body">
              <div className="dashboard-active-file-main">
                <div>
                  <strong>{activeJob.source_filename ?? activeJob.source_path?.split("/").pop() ?? activeJob.id}</strong>
                  <p>{activeJob.worker_name ?? worker?.worker_name ?? "Worker not assigned"}</p>
                </div>
                <Link className="button button-secondary button-small" to={APP_ROUTES.jobDetail(activeJob.id)}>
                  Open job
                </Link>
              </div>
              <div className="dashboard-progress" aria-label="Active transcoding progress">
                <span style={{ width: `${activeProgress ?? 0}%` }} />
              </div>
              <div className="dashboard-progress-meta">
                <strong className="dashboard-progress-value">{activeProgress == null ? "Progress unavailable" : `${activeProgress}% complete`}</strong>
                <span>{activeJob.progress_stage ? titleCase(activeJob.progress_stage) : "Processing"}</span>
              </div>
            </div>
          ) : (
            <div className="dashboard-idle-state">
              <strong>System Idle</strong>
              <p>Waiting for queued jobs or scheduled watcher activity.</p>
            </div>
          )}
        </article>
      </section>

      <section className="dashboard-widget">
        <div className="dashboard-widget-header">
          <div>
            <h2>System & Nodes</h2>
            <p>General health checks without hardware telemetry noise.</p>
          </div>
          <Link className="text-link" to={APP_ROUTES.system}>Open system</Link>
        </div>

        <div className="dashboard-node-grid">
          {systemNodes.map((node) => (
            <div key={node.name} className="dashboard-node-row">
              <div className={`dashboard-status-dot dashboard-status-dot-${node.tone}`} aria-hidden="true" />
              <div>
                <strong>{node.name}</strong>
                <p>{node.detail}</p>
              </div>
              <span className={`dashboard-node-pill dashboard-node-pill-${node.tone}`}>{node.status}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatusSummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "danger" | "warning" | "success";
}) {
  return (
    <div className={`dashboard-breakdown-card dashboard-breakdown-card-${tone}`}>
      <span className="metric-label">{label}</span>
      <strong>{formatInteger(value)}</strong>
    </div>
  );
}

function buildActionItems(
  runtime: RuntimeStatus | undefined,
  storage: StorageStatus | undefined,
  worker: WorkerStatus | undefined,
): ActionItem[] {
  const items: ActionItem[] = [];
  if (runtime?.storage_setup_incomplete || storage?.status === "degraded" || storage?.status === "failed") {
    items.push({
      title: "Storage still needs setup.",
      description: storage?.summary ?? "Setup storage mounts before running automation.",
      to: APP_ROUTES.config,
    });
  }
  if (worker && (!worker.configured || !worker.enabled || !worker.eligible)) {
    items.push({
      title: worker.configured ? "Review worker node." : "Configure first worker node.",
      description: worker.eligibility_summary || worker.summary,
      to: APP_ROUTES.workers,
    });
  }
  if (runtime && (!runtime.db_reachable || !runtime.schema_reachable)) {
    items.push({
      title: "Database requires attention.",
      description: runtime.summary,
      to: APP_ROUTES.system,
    });
  }
  return items;
}

function buildSystemNodes(
  runtime: RuntimeStatus | undefined,
  storage: StorageStatus | undefined,
  worker: WorkerStatus | undefined,
): SystemNode[] {
  return [
    {
      name: "Database",
      detail: runtime?.db_reachable ? "Schema reachable and accepting requests." : "Database connection is unavailable.",
      status: runtime?.db_reachable ? "Nominal" : "Offline",
      tone: runtime?.db_reachable ? "nominal" : "offline",
    },
    {
      name: "Storage",
      detail: storage?.summary ?? "Storage status unavailable.",
      status: titleCase(storage?.status ?? "unknown"),
      tone: healthTone(storage?.status),
    },
    {
      name: worker?.worker_name ?? "Worker Node",
      detail: worker?.summary ?? "Worker status unavailable.",
      status: workerStatusLabel(worker),
      tone: workerTone(worker),
    },
  ];
}

function workerStatusLabel(worker: WorkerStatus | undefined) {
  if (!worker) {
    return "Offline";
  }
  if (worker.current_job_id || worker.queue_health.running_count > 0) {
    return "Processing";
  }
  if (!worker.enabled || !worker.available) {
    return "Offline";
  }
  if (!worker.eligible || worker.status === "degraded") {
    return "Degraded";
  }
  return "Idle";
}

function workerTone(worker: WorkerStatus | undefined): SystemNode["tone"] {
  if (!worker || !worker.enabled || !worker.available) {
    return "offline";
  }
  if (worker.current_job_id || worker.queue_health.running_count > 0) {
    return "processing";
  }
  if (!worker.eligible || worker.status === "degraded" || worker.status === "failed") {
    return "degraded";
  }
  return "idle";
}

function healthTone(status: string | undefined): SystemNode["tone"] {
  if (status === "healthy") {
    return "nominal";
  }
  if (status === "failed") {
    return "offline";
  }
  if (status === "degraded") {
    return "degraded";
  }
  return "idle";
}

function pickActiveJob(jobs: JobSummary[], currentJobId?: string | null) {
  if (currentJobId) {
    return jobs.find((job) => job.id === currentJobId) ?? jobs[0] ?? null;
  }
  return jobs[0] ?? null;
}

function clampProgress(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return null;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

function countByValue(items: Array<{ value: string; count: number }>, value: string) {
  return items.find((item) => item.value === value)?.count ?? 0;
}

function toCountMap(items: Array<{ value: string; count: number }>) {
  return items.reduce<Record<string, number>>((accumulator, item) => {
    accumulator[item.value] = item.count;
    return accumulator;
  }, {});
}

function formatInteger(value: number | null | undefined) {
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 }).format(value ?? 0);
}

function formatAverage(value: number | null | undefined, label: string) {
  if (value == null || Number.isNaN(value)) {
    return `${label} unavailable`;
  }
  return `${new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(value)} ${label.toLowerCase()}`;
}
