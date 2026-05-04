import { Component, type ErrorInfo, type ReactNode } from "react";
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

type DashboardWidgetBoundaryProps = {
  title: string;
  resetKey: string | number;
  children: ReactNode;
};

type DashboardWidgetBoundaryState = {
  failed: boolean;
};

export class DashboardWidgetBoundary extends Component<DashboardWidgetBoundaryProps, DashboardWidgetBoundaryState> {
  state: DashboardWidgetBoundaryState = { failed: false };

  static getDerivedStateFromError(): DashboardWidgetBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("Dashboard widget failed to render.", { error, componentStack: info.componentStack });
  }

  componentDidUpdate(previousProps: DashboardWidgetBoundaryProps) {
    if (this.state.failed && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return (
        <article className="dashboard-widget">
          <ErrorPanel
            title={`${this.props.title} unavailable`}
            message="This dashboard section could not render the latest live data. The rest of the dashboard is still available."
          />
        </article>
      );
    }

    return this.props.children;
  }
}

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
    (analyticsQuery.isLoading && !analyticsQuery.data && !analyticsQuery.error) ||
    (workerQuery.isLoading && !workerQuery.data && !workerQuery.error) ||
    (runtimeQuery.isLoading && !runtimeQuery.data && !runtimeQuery.error) ||
    (storageQuery.isLoading && !storageQuery.data && !storageQuery.error) ||
    (runningJobsQuery.isLoading && !runningJobsQuery.data && !runningJobsQuery.error);
  const warnings = [
    dashboardWarning("Analytics", analyticsQuery.error),
    dashboardWarning("Worker status", workerQuery.error),
    dashboardWarning("Runtime status", runtimeQuery.error),
    dashboardWarning("Storage status", storageQuery.error),
    dashboardWarning("Running jobs", runningJobsQuery.error),
  ].filter((item): item is string => Boolean(item));

  if (loading) {
    return <LoadingBlock label="Loading dashboard" />;
  }

  void error;

  const analytics = analyticsQuery.data;
  const worker = workerQuery.data;
  const runtime = runtimeQuery.data;
  const storage = storageQuery.data;
  const runningJobs = sanitiseJobs(runningJobsQuery.data?.items);
  const jobStatusCounts = toCountMap(analytics?.overview?.jobs_by_status ?? []);
  const dashboardCounts = analytics?.queue_counts;
  const completedJobCount = safeNumber(dashboardCounts?.completed, jobStatusCounts.completed ?? 0);
  const manualReviewCount = safeNumber(dashboardCounts?.manual_review, jobStatusCounts.manual_review ?? 0);
  const failedJobCount = safeNumber(dashboardCounts?.failed, jobStatusCounts.failed ?? 0);
  const interruptedJobCount = safeNumber(dashboardCounts?.interrupted, jobStatusCounts.interrupted ?? 0);
  const runningJobCount = safeNumber(dashboardCounts?.running, jobStatusCounts.running ?? 0);
  const totalTranscodes = countByValue(analytics?.overview?.plans_by_action ?? [], "transcode");
  const processedFileCount = safeNumber(analytics?.overview?.processed_file_count, completedJobCount);
  const averageProcessedPerDay = nullableNumber(analytics?.overview?.average_processed_per_day);
  const totalSpaceSaved = safeNumber(analytics?.storage?.total_space_saved_bytes, 0);
  const averageSavedPerDay = nullableNumber(analytics?.storage?.average_space_saved_per_day_bytes);
  const totalAudioRemoved = safeNumber(analytics?.media?.total_audio_tracks_removed, 0);
  const totalSubtitleRemoved = safeNumber(analytics?.media?.total_subtitle_tracks_removed, 0);
  const actionItems = buildActionItems(runtime, storage, worker);
  const activeJob = pickActiveJob(runningJobs, worker?.current_job_id);
  const activeProgress = clampProgress(activeJob?.progress_percent ?? worker?.current_progress_percent ?? null);
  const systemNodes = buildSystemNodes(runtime, storage, worker);
  const historicalMetricsResetKey = analyticsQuery.dataUpdatedAt;
  const transcodingOutcomesResetKey = `${analyticsQuery.dataUpdatedAt}:${runningJobsQuery.dataUpdatedAt}`;
  const activeFileResetKey = [
    workerQuery.dataUpdatedAt,
    runningJobsQuery.dataUpdatedAt,
    activeJob?.id ?? "none",
    activeJob?.status ?? "none",
    activeProgress ?? "none",
  ].join(":");
  const systemNodesResetKey = [
    workerQuery.dataUpdatedAt,
    runtimeQuery.dataUpdatedAt,
    storageQuery.dataUpdatedAt,
  ].join(":");

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Dashboard"
        title="Dashboard"
        description="Library, jobs, review, and storage at a glance."
      />

      {warnings.length > 0 ? (
        <div className="card-stack" aria-label="Dashboard warnings">
          {warnings.map((warning) => (
            <ErrorPanel key={warning} title="Dashboard data is partially unavailable" message={warning} />
          ))}
        </div>
      ) : null}

      {actionItems.length > 0 ? (
        <section className="dashboard-action-banner" role="note" aria-label="Action required">
          <div>
            <span className="section-eyebrow">Action Required</span>
            <h2>Finish critical setup.</h2>
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

      <DashboardWidgetBoundary title="Historical metrics" resetKey={historicalMetricsResetKey}>
        <section className="dashboard-analytics-row" aria-label="Historical processing metrics">
          <Link className="dashboard-metric-card dashboard-card-link" to={`${APP_ROUTES.jobs}?status=completed&tab=completed`}>
            <span className="metric-label">Files Processed</span>
            <strong>{formatInteger(processedFileCount)}</strong>
            <small>{formatAverage(averageProcessedPerDay, "Average per day")}</small>
          </Link>
          <Link className="dashboard-metric-card dashboard-card-link" to={APP_ROUTES.system}>
            <span className="metric-label">Storage Saved</span>
            <strong>{formatBytes(totalSpaceSaved)}</strong>
            <small>{averageSavedPerDay == null ? "Average saved per day unavailable" : `${formatBytes(averageSavedPerDay)} average saved per day`}</small>
          </Link>
          <Link className="dashboard-metric-card dashboard-card-link" to={`${APP_ROUTES.jobs}?status=completed&tab=completed`}>
            <span className="metric-label">Media Cleaned</span>
            <strong>{formatInteger(totalAudioRemoved)} audio</strong>
            <small>{formatInteger(totalSubtitleRemoved)} subtitles removed</small>
          </Link>
        </section>
      </DashboardWidgetBoundary>

      <section className="dashboard-command-grid" aria-label="Transcoding command center">
        <DashboardWidgetBoundary title="Transcoding outcomes" resetKey={transcodingOutcomesResetKey}>
          <article className="dashboard-widget">
            <div className="dashboard-widget-header">
              <div>
                <h2>Transcoding Outcomes</h2>
                <p>Queue health and actions.</p>
              </div>
              <Link className="text-link" to={APP_ROUTES.jobs}>Open jobs</Link>
            </div>

            <div className="dashboard-outcome-top">
              <Link className={`dashboard-outcome-card dashboard-card-link${manualReviewCount > 0 ? " dashboard-outcome-card-attention" : ""}`} to={`${APP_ROUTES.review}?status=open`}>
                <span className="metric-label">Manual Review</span>
                <strong>{formatInteger(manualReviewCount)}</strong>
              </Link>
              <Link className="dashboard-outcome-card dashboard-card-link" to={`${APP_ROUTES.jobs}?status=completed&tab=completed`}>
                <span className="metric-label">Total Transcodes</span>
                <strong>{formatInteger(totalTranscodes)}</strong>
              </Link>
            </div>

            <div className="dashboard-breakdown-grid">
              <StatusSummaryCard label="Failed" value={failedJobCount} tone="danger" to={`${APP_ROUTES.jobs}?status=failed&tab=problem`} />
              <StatusSummaryCard label="Interrupted" value={interruptedJobCount} tone="warning" to={`${APP_ROUTES.jobs}?status=interrupted&tab=problem`} />
              <StatusSummaryCard label="Running" value={runningJobCount} tone="success" to={`${APP_ROUTES.jobs}?status=running&tab=active`} />
            </div>
          </article>
        </DashboardWidgetBoundary>

        <DashboardWidgetBoundary title="Active file" resetKey={activeFileResetKey}>
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
                    <strong>{activeJobLabel(activeJob)}</strong>
                    <p>{safeText(activeJob.worker_name ?? worker?.worker_name, "Worker not assigned")}</p>
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
                  <span>{safeTitleCase(activeJob.progress_stage, "Processing")}</span>
                </div>
              </div>
            ) : (
              <div className="dashboard-idle-state">
                <strong>System Idle</strong>
                <p>Waiting for queued jobs or scheduled watcher activity.</p>
              </div>
            )}
          </article>
        </DashboardWidgetBoundary>
      </section>

      <DashboardWidgetBoundary title="System nodes" resetKey={systemNodesResetKey}>
        <section className="dashboard-widget">
          <div className="dashboard-widget-header">
            <div>
              <h2>System & Nodes</h2>
              <p>Current system health overview.</p>
            </div>
            <Link className="text-link" to={APP_ROUTES.system}>Open system</Link>
          </div>

          <div className="dashboard-node-grid">
            {systemNodes.map((node) => (
              <Link key={node.name} className="dashboard-node-row dashboard-card-link" to={systemNodeRoute(node, worker)}>
                <div className={`dashboard-status-dot dashboard-status-dot-${node.tone}`} aria-hidden="true" />
                <div>
                  <strong>{node.name}</strong>
                  <p>{node.detail}</p>
                </div>
                <span className={`dashboard-node-pill dashboard-node-pill-${node.tone}`}>{node.status}</span>
              </Link>
            ))}
          </div>
        </section>
      </DashboardWidgetBoundary>
    </div>
  );
}

function StatusSummaryCard({
  label,
  value,
  tone,
  to,
}: {
  label: string;
  value: number;
  tone: "danger" | "warning" | "success";
  to: string;
}) {
  return (
    <Link className={`dashboard-breakdown-card dashboard-card-link dashboard-breakdown-card-${tone}`} to={to}>
      <span className="metric-label">{label}</span>
      <strong>{formatInteger(value)}</strong>
    </Link>
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
      description: safeText(storage?.summary, "Setup storage mounts before running automation."),
      to: APP_ROUTES.config,
    });
  }
  if (worker && (!worker.configured || !worker.enabled || !worker.eligible)) {
    items.push({
      title: worker.configured ? "Review worker node." : "Configure first worker node.",
      description: safeText(worker.eligibility_summary || worker.summary, "Worker status is unavailable."),
      to: APP_ROUTES.workers,
    });
  }
  if (runtime && (!runtime.db_reachable || !runtime.schema_reachable)) {
    items.push({
      title: "Database requires attention.",
      description: safeText(runtime.summary, "Runtime status is unavailable."),
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
      detail: safeText(storage?.summary, "Storage status unavailable."),
      status: safeTitleCase(storage?.status, "Unknown"),
      tone: healthTone(storage?.status),
    },
    {
      name: safeText(worker?.worker_name, "Worker Node"),
      detail: safeText(worker?.summary, "Worker status unavailable."),
      status: workerStatusLabel(worker),
      tone: workerTone(worker),
    },
  ];
}

function systemNodeRoute(node: SystemNode, worker: WorkerStatus | undefined) {
  if (node.name === "Storage") {
    return APP_ROUTES.system;
  }
  if (node.name === "Database") {
    return APP_ROUTES.system;
  }
  if (worker?.worker_id) {
    return APP_ROUTES.workerDetail(worker.worker_id);
  }
  return APP_ROUTES.workers;
}

function workerStatusLabel(worker: WorkerStatus | undefined) {
  if (!worker) {
    return "Offline";
  }
  if (workerHasRunningJob(worker)) {
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
  if (workerHasRunningJob(worker)) {
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

function clampProgress(value: number | null | undefined) {
  if (!isFiniteNumber(value)) {
    return null;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

function countByValue(items: Array<{ value: string; count: number }>, value: string) {
  return safeNumber(items.find((item) => item.value === value)?.count, 0);
}

function toCountMap(items: Array<{ value: string; count: number }>) {
  return items.reduce<Record<string, number>>((accumulator, item) => {
    if (typeof item.value === "string") {
      accumulator[item.value] = safeNumber(item.count, 0);
    }
    return accumulator;
  }, {});
}

function formatInteger(value: number | null | undefined) {
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 }).format(safeNumber(value, 0));
}

function formatAverage(value: number | null | undefined, label: string) {
  if (value == null || Number.isNaN(value)) {
    return `${label} unavailable`;
  }
  return `${new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(value)} ${label.toLowerCase()}`;
}

function activeJobLabel(job: JobSummary) {
  return safeText(job.source_filename, safeText(job.source_path?.split("/").filter(Boolean).at(-1), job.id));
}

function workerHasRunningJob(worker: WorkerStatus) {
  return Boolean(worker.current_job_id) || safeNumber(worker.queue_health?.running_count, 0) > 0;
}

function dashboardWarning(label: string, error: unknown) {
  if (!(error instanceof Error)) {
    return null;
  }
  return `${label}: ${error.message}`;
}

function sanitiseJobs(items: JobSummary[] | undefined): JobSummary[] {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.filter((item) =>
    Boolean(item && typeof item.id === "string" && item.id && typeof item.status === "string" && item.status),
  );
}

function safeText(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function safeTitleCase(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? titleCase(value) : fallback;
}

function safeNumber(value: unknown, fallback = 0) {
  return isFiniteNumber(value) ? value : fallback;
}

function nullableNumber(value: unknown) {
  return isFiniteNumber(value) ? value : null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
