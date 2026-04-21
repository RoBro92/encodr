import { Link } from "react-router-dom";

import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatCard } from "../../components/StatCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useAnalyticsDashboardQuery,
  usePlanFileMutation,
  useProbeFileMutation,
  useRunWorkerOnceMutation,
  useRuntimeStatusQuery,
  useStorageStatusQuery,
  useWorkerStatusQuery,
} from "../../lib/api/hooks";
import { formatBytes, formatDateTime, titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

export function DashboardPage() {
  const analyticsQuery = useAnalyticsDashboardQuery();
  const workerQuery = useWorkerStatusQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();
  const runOnceMutation = useRunWorkerOnceMutation();

  const error =
    analyticsQuery.error ??
    workerQuery.error ??
    runtimeQuery.error ??
    storageQuery.error;
  const loading =
    analyticsQuery.isLoading ||
    workerQuery.isLoading ||
    runtimeQuery.isLoading ||
    storageQuery.isLoading;

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
  const jobStatusCounts = toCountMap(analytics?.overview.jobs_by_status ?? []);
  const queuedJobCount = (jobStatusCounts.pending ?? 0) + (jobStatusCounts.running ?? 0);
  const completedJobCount = jobStatusCounts.completed ?? 0;
  const failedJobCount = jobStatusCounts.failed ?? 0;
  const recentItems = analytics
    ? [...analytics.recent.recent_failed_jobs, ...analytics.recent.recent_completed_jobs]
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
        .slice(0, 5)
    : [];

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Dashboard"
        title="Dashboard"
        description="A quick view of files, jobs, review items, and storage."
        actions={
          <button
            className="button button-primary"
            type="button"
            onClick={() => runOnceMutation.mutate()}
            disabled={runOnceMutation.isPending}
          >
            {runOnceMutation.isPending ? "Running worker…" : "Run worker once"}
          </button>
        }
      />

      {runOnceMutation.error instanceof Error ? (
        <ErrorPanel title="Worker run failed" message={runOnceMutation.error.message} />
      ) : null}

      <section className="stats-grid">
        <StatCard label="Tracked files" value={analytics?.overview.total_tracked_files ?? 0} />
        <StatCard label="Queued or running jobs" value={queuedJobCount} tone="warning" />
        <StatCard label="Completed jobs" value={completedJobCount} tone="positive" />
        <StatCard label="Failed jobs" value={failedJobCount} tone="danger" />
        <StatCard label="Protected files" value={analytics?.overview.protected_file_count ?? 0} />
        <StatCard label="4K files" value={analytics?.overview.four_k_file_count ?? 0} />
      </section>

      <section className="dashboard-grid">
        <SectionCard title="Start here" subtitle="Pick the next step.">
          <div className="list-stack">
            <Link className="list-row" to={APP_ROUTES.files}>
              <div>
                <strong>Open Library</strong>
                <p>Browse folders, scan a location, and run a dry run.</p>
              </div>
            </Link>
            <Link className="list-row" to={APP_ROUTES.review}>
              <div>
                <strong>Check Manual Review</strong>
                <p>Approve or hold files that need attention.</p>
              </div>
            </Link>
            <Link className="list-row" to={APP_ROUTES.config}>
              <div>
                <strong>Check Setup</strong>
                <p>Confirm your Movies and TV roots and storage status.</p>
              </div>
            </Link>
          </div>
        </SectionCard>

        <SectionCard title="Outcomes" subtitle="Current job and plan results.">
          {analytics ? (
            <div className="card-stack">
              <div className="badge-list">
                {analytics.overview.plans_by_action.map((item) => (
                  <div key={item.value} className="metric-pill">
                    <span>{titleCase(item.value)}</span>
                    <strong>{item.count}</strong>
                  </div>
                ))}
              </div>
              <div className="badge-list">
                {analytics.outcomes.jobs_by_status.map((item) => (
                  <div key={item.value} className="metric-pill">
                    <StatusBadge value={item.value} />
                    <strong>{item.count}</strong>
                  </div>
                ))}
              </div>
              <Link className="text-link" to={APP_ROUTES.reports}>Open reports</Link>
            </div>
          ) : (
            <EmptyState title="No analytics yet" message="Run probe, planning, and jobs to build reporting history." />
          )}
        </SectionCard>

        <SectionCard title="Space saved" subtitle="Measured completed jobs only.">
          {analytics ? (
            <div className="card-stack">
              <p className="metric-lead">{formatBytes(analytics.storage.total_space_saved_bytes)} saved</p>
              <p className="muted-copy">
                Average per completed measurable job:{" "}
                <strong>{formatBytes(analytics.storage.average_space_saved_bytes)}</strong>
              </p>
              <div className="metric-grid">
                {analytics.storage.savings_by_action.map((item) => (
                  <div key={item.action} className="metric-panel">
                    <span className="metric-label">{titleCase(item.action)}</span>
                    <strong>{formatBytes(item.space_saved_bytes)}</strong>
                    <span className="metric-subtle">{item.job_count} measurable jobs</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </SectionCard>

        <SectionCard title="Worker" subtitle="Current worker state.">
          {worker ? (
            <div className="card-stack">
              <div className="info-strip">
                <StatusBadge value={worker.last_result_status ?? "idle"} />
                <span>{worker.worker_name}</span>
              </div>
              <p className="muted-copy">
                Queue: <strong>{worker.local_worker_queue}</strong> · Processed jobs:{" "}
                <strong>{worker.processed_jobs}</strong>
              </p>
              <p className="muted-copy">
                Last completed run: <strong>{formatDateTime(worker.last_run_completed_at)}</strong>
              </p>
              <Link className="text-link" to={APP_ROUTES.system}>
                Open system status
              </Link>
            </div>
          ) : (
            <EmptyState title="No worker data" message="Worker status is not available yet." />
          )}
        </SectionCard>

        <SectionCard title="System" subtitle="Runtime and storage status.">
          {runtime && storage ? (
            <div className="card-stack">
              <div className="info-strip">
                <StatusBadge value={runtime.db_reachable ? "ok" : "failed"} />
                <span>Database reachable: {runtime.db_reachable ? "Yes" : "No"}</span>
              </div>
              {runtime.storage_setup_incomplete ? (
                <div className="info-strip" role="note">
                  <strong>Storage still needs setup.</strong>
                  <span>
                    Encodr expects your media library at <code>{storage.standard_media_root}</code>. You can keep setting up the app, then mount storage when ready.
                  </span>
                </div>
              ) : null}
              <p className="muted-copy">
                Scratch path writable: <strong>{storage.scratch.writable ? "Yes" : "No"}</strong>
              </p>
              <p className="muted-copy">
                Auth enabled: <strong>{runtime.auth_enabled ? "Yes" : "No"}</strong>
              </p>
            </div>
          ) : null}
        </SectionCard>

        <SectionCard title="Recent activity" subtitle="Latest completed and failed jobs.">
          {recentItems.length > 0 ? (
            <div className="list-stack">
              {recentItems.map((item) => (
                <Link key={item.job_id} className="list-row" to={APP_ROUTES.jobDetail(item.job_id)}>
                  <div>
                    <strong>{item.file_name}</strong>
                    <p>{formatDateTime(item.updated_at)}</p>
                  </div>
                  <div className="list-row-meta">
                    <span className="muted-copy">{titleCase(item.action)}</span>
                    <StatusBadge value={item.status} />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title="No reporting history yet" message="Completed and failed jobs will appear here once the worker has processed them." />
          )}
        </SectionCard>

        <SectionCard title="Media summary" subtitle="A quick view from recent probe and plan data.">
          {analytics ? (
            <div className="metric-grid">
              <div className="metric-panel">
                <span className="metric-label">English audio present</span>
                <strong>{analytics.media.latest_probe_english_audio_count}</strong>
              </div>
              <div className="metric-panel">
                <span className="metric-label">Forced subtitle intent</span>
                <strong>{analytics.media.latest_plan_forced_subtitle_intent_count}</strong>
              </div>
              <div className="metric-panel">
                <span className="metric-label">Surround preserved</span>
                <strong>{analytics.media.latest_plan_surround_preservation_intent_count}</strong>
              </div>
              <div className="metric-panel">
                <span className="metric-label">Atmos preserved</span>
                <strong>{analytics.media.latest_plan_atmos_preservation_intent_count}</strong>
              </div>
            </div>
          ) : null}
        </SectionCard>
      </section>
    </div>
  );
}

function toCountMap(items: Array<{ value: string; count: number }>) {
  return items.reduce<Record<string, number>>((accumulator, item) => {
    accumulator[item.value] = item.count;
    return accumulator;
  }, {});
}
