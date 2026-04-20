import { Link } from "react-router-dom";

import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { PathActionForm } from "../../components/PathActionForm";
import { SectionCard } from "../../components/SectionCard";
import { StatCard } from "../../components/StatCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useFilesQuery,
  useJobsQuery,
  usePlanFileMutation,
  useProbeFileMutation,
  useRunWorkerOnceMutation,
  useRuntimeStatusQuery,
  useStorageStatusQuery,
  useWorkerStatusQuery,
} from "../../lib/api/hooks";
import { APP_ROUTES } from "../../lib/utils/routes";
import { formatDateTime } from "../../lib/utils/format";

export function DashboardPage() {
  const filesQuery = useFilesQuery({ limit: 200 });
  const jobsQuery = useJobsQuery({ limit: 50 });
  const workerQuery = useWorkerStatusQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();
  const probeMutation = useProbeFileMutation();
  const planMutation = usePlanFileMutation();
  const runOnceMutation = useRunWorkerOnceMutation();

  const error =
    filesQuery.error ??
    jobsQuery.error ??
    workerQuery.error ??
    runtimeQuery.error ??
    storageQuery.error;

  const loading =
    filesQuery.isLoading ||
    jobsQuery.isLoading ||
    workerQuery.isLoading ||
    runtimeQuery.isLoading ||
    storageQuery.isLoading;

  if (loading) {
    return <LoadingBlock label="Loading dashboard" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load the dashboard" message={error.message} />;
  }

  const files = filesQuery.data?.items ?? [];
  const jobs = jobsQuery.data?.items ?? [];
  const queuedJobs = jobs.filter((job) => job.status === "pending" || job.status === "running");
  const completedJobs = jobs.filter((job) => job.status === "completed");
  const failedJobs = jobs.filter((job) => job.status === "failed");
  const protectedFiles = files.filter((file) => file.is_protected);
  const fourKFiles = files.filter((file) => file.is_4k);
  const worker = workerQuery.data;
  const runtime = runtimeQuery.data;
  const storage = storageQuery.data;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Dashboard"
        title="Operational overview"
        description="A concise summary of tracked files, job flow, local worker state, and runtime health."
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

      {probeMutation.error instanceof Error ? (
        <ErrorPanel title="Probe request failed" message={probeMutation.error.message} />
      ) : null}
      {planMutation.error instanceof Error ? (
        <ErrorPanel title="Plan request failed" message={planMutation.error.message} />
      ) : null}
      {runOnceMutation.error instanceof Error ? (
        <ErrorPanel title="Worker run failed" message={runOnceMutation.error.message} />
      ) : null}

      <section className="stats-grid">
        <StatCard label="Tracked files" value={files.length} />
        <StatCard label="Queued or running jobs" value={queuedJobs.length} tone="warning" />
        <StatCard label="Completed jobs" value={completedJobs.length} tone="positive" />
        <StatCard label="Failed jobs" value={failedJobs.length} tone="danger" />
        <StatCard label="Protected files" value={protectedFiles.length} />
        <StatCard label="4K files" value={fourKFiles.length} />
      </section>

      <section className="dashboard-grid">
        <SectionCard title="Quick actions" subtitle="Operator-friendly entry points for common tasks.">
          <div className="card-stack">
            <PathActionForm
              label="Probe source path"
              placeholder="/media/Movies/Example Film (2024).mkv"
              submitLabel="Probe file"
              submittingLabel="Probing…"
              onSubmit={async (sourcePath) => {
                await probeMutation.mutateAsync({ source_path: sourcePath });
              }}
            />
            <PathActionForm
              label="Plan source path"
              placeholder="/media/TV/Example Show/Season 01/Example S01E01.mkv"
              submitLabel="Plan file"
              submittingLabel="Planning…"
              onSubmit={async (sourcePath) => {
                await planMutation.mutateAsync({ source_path: sourcePath });
              }}
            />
            {runOnceMutation.data ? (
              <div className="info-strip">
                <StatusBadge value={runOnceMutation.data.final_status ?? "idle"} />
                <span>
                  {runOnceMutation.data.processed_job
                    ? `Processed job ${runOnceMutation.data.job_id ?? "unknown"}`
                    : "No pending job was available."}
                </span>
              </div>
            ) : null}
          </div>
        </SectionCard>

        <SectionCard title="Local worker" subtitle="Current local-only worker state.">
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

        <SectionCard title="Runtime" subtitle="Conservative operational checks from the current API.">
          {runtime && storage ? (
            <div className="card-stack">
              <div className="info-strip">
                <StatusBadge value={runtime.db_reachable ? "ok" : "failed"} />
                <span>Database reachable: {runtime.db_reachable ? "Yes" : "No"}</span>
              </div>
              <p className="muted-copy">
                Scratch path writable: <strong>{storage.scratch.writable ? "Yes" : "No"}</strong>
              </p>
              <p className="muted-copy">
                Auth enabled: <strong>{runtime.auth_enabled ? "Yes" : "No"}</strong>
              </p>
            </div>
          ) : null}
        </SectionCard>

        <SectionCard title="Latest jobs" subtitle="Recent activity from the existing jobs API.">
          {jobs.length > 0 ? (
            <div className="list-stack">
              {jobs.slice(0, 5).map((job) => (
                <Link key={job.id} className="list-row" to={APP_ROUTES.jobDetail(job.id)}>
                  <div>
                    <strong>{job.id.slice(0, 8)}</strong>
                    <p>{formatDateTime(job.updated_at)}</p>
                  </div>
                  <StatusBadge value={job.status} />
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title="No jobs yet" message="Create or run a plan to populate the queue." />
          )}
        </SectionCard>
      </section>
    </div>
  );
}
