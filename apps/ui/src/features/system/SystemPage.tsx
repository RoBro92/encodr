import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useRunWorkerOnceMutation,
  useRuntimeStatusQuery,
  useStorageStatusQuery,
  useWorkerSelfTestMutation,
  useWorkerStatusQuery,
} from "../../lib/api/hooks";
import { formatBytes, formatDateTime, formatDurationSeconds, formatRelativeBoolean } from "../../lib/utils/format";

export function SystemPage() {
  const workerQuery = useWorkerStatusQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();
  const runOnceMutation = useRunWorkerOnceMutation();
  const selfTestMutation = useWorkerSelfTestMutation();

  const error = workerQuery.error ?? runtimeQuery.error ?? storageQuery.error;
  if (workerQuery.isLoading || runtimeQuery.isLoading || storageQuery.isLoading) {
    return <LoadingBlock label="Loading system status" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load system status" message={error.message} />;
  }

  const worker = workerQuery.data;
  const runtime = runtimeQuery.data;
  const storage = storageQuery.data;

  async function refreshHealth() {
    await Promise.all([
      workerQuery.refetch(),
      runtimeQuery.refetch(),
      storageQuery.refetch(),
    ]);
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="System"
        title="Worker and storage health"
        description="Operational diagnostics for the local worker, runtime dependencies, queue health, and configured storage paths."
        actions={
          <div className="page-actions">
            <button
              className="button button-secondary"
              type="button"
              onClick={() => {
                void refreshHealth();
              }}
            >
              Refresh health
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => selfTestMutation.mutate()}
              disabled={selfTestMutation.isPending}
            >
              {selfTestMutation.isPending ? "Running self-test…" : "Run self-test"}
            </button>
            <button
              className="button button-primary"
              type="button"
              onClick={() => runOnceMutation.mutate()}
              disabled={runOnceMutation.isPending}
            >
              {runOnceMutation.isPending ? "Running worker…" : "Run worker once"}
            </button>
          </div>
        }
      />

      {runOnceMutation.error instanceof Error ? (
        <ErrorPanel title="Worker run failed" message={runOnceMutation.error.message} />
      ) : null}
      {selfTestMutation.error instanceof Error ? (
        <ErrorPanel title="Worker self-test failed" message={selfTestMutation.error.message} />
      ) : null}

      <section className="stats-grid">
        <HealthStatCard label="Worker" status={worker?.status} value={worker?.summary ?? "Not available"} />
        <HealthStatCard label="Runtime" status={runtime?.status} value={runtime?.summary ?? "Not available"} />
        <HealthStatCard label="Storage" status={storage?.status} value={storage?.summary ?? "Not available"} />
        <HealthStatCard
          label="Pending jobs"
          status={worker?.queue_health.status}
          value={worker?.queue_health.pending_count ?? 0}
        />
      </section>

      <section className="dashboard-grid">
        <SectionCard title="Worker health" subtitle="Local-only worker state, binary availability, and queue diagnostics.">
          {worker ? (
            <div className="card-stack">
              <div className="info-strip">
                <StatusBadge value={worker.status} />
                <span>{worker.summary}</span>
              </div>
              <div className="metric-grid">
                <HealthMetric label="Mode" value={worker.mode} />
                <HealthMetric label="Queue" value={worker.local_worker_queue} />
                <HealthMetric label="Available" value={formatRelativeBoolean(worker.available)} />
                <HealthMetric label="Processed jobs" value={String(worker.processed_jobs)} />
              </div>
              <div className="status-grid">
                <BinaryCard title="FFmpeg" item={worker.ffmpeg} />
                <BinaryCard title="FFprobe" item={worker.ffprobe} />
              </div>
              <QueueHealthCard workerStatus={worker} />
            </div>
          ) : null}
        </SectionCard>

        <SectionCard title="Runtime health" subtitle="Runtime dependencies, auth baseline, and config source visibility.">
          {runtime ? (
            <div className="card-stack">
              <div className="info-strip">
                <StatusBadge value={runtime.status} />
                <span>{runtime.summary}</span>
              </div>
              <div className="metric-grid">
                <HealthMetric label="Version" value={runtime.version} />
                <HealthMetric label="Environment" value={runtime.environment} />
                <HealthMetric label="DB reachable" value={formatRelativeBoolean(runtime.db_reachable)} />
                <HealthMetric label="Schema reachable" value={formatRelativeBoolean(runtime.schema_reachable)} />
                <HealthMetric label="Auth enabled" value={formatRelativeBoolean(runtime.auth_enabled)} />
                <HealthMetric label="User count" value={runtime.user_count == null ? "Not available" : String(runtime.user_count)} />
              </div>
              <div className="card-stack">
                <strong>Config sources</strong>
                <dl className="key-value-list">
                  {Object.entries(runtime.config_sources).map(([key, value]) => (
                    <div key={key} className="key-value-row">
                      <dt>{key}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              {runtime.warnings.length > 0 ? (
                <div className="card-stack">
                  <strong>Warnings</strong>
                  <div className="list-stack">
                    {runtime.warnings.map((warning) => (
                      <div key={warning} className="list-row">
                        <span>{warning}</span>
                        <StatusBadge value="degraded" />
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </SectionCard>
      </section>

      <SectionCard title="Storage health" subtitle="Configured scratch, data, and media paths with free-space and access diagnostics.">
        {storage ? (
          <div className="card-stack">
            <div className="info-strip">
              <StatusBadge value={storage.status} />
              <span>{storage.summary}</span>
            </div>
            <div className="status-grid">
              {[storage.scratch, storage.data_dir, ...storage.media_mounts].map((pathStatus) => (
                <article key={pathStatus.role + pathStatus.path} className="status-card">
                  <div className="badge-row">
                    <StatusBadge value={pathStatus.status} />
                    <strong>{pathStatus.role.replace("_", " ")}</strong>
                  </div>
                  <p className="muted-copy">{pathStatus.path}</p>
                  <p className="muted-copy">{pathStatus.message}</p>
                  <div className="metric-grid">
                    <HealthMetric label="Readable" value={formatRelativeBoolean(pathStatus.readable)} />
                    <HealthMetric label="Writable" value={formatRelativeBoolean(pathStatus.writable)} />
                    <HealthMetric label="Free space" value={formatBytes(pathStatus.free_space_bytes)} />
                    <HealthMetric label="Total space" value={formatBytes(pathStatus.total_space_bytes)} />
                  </div>
                </article>
              ))}
            </div>
            {storage.warnings.length > 0 ? (
              <div className="card-stack">
                <strong>Storage warnings</strong>
                <div className="list-stack">
                  {storage.warnings.map((warning) => (
                    <div key={warning} className="list-row">
                      <span>{warning}</span>
                      <StatusBadge value="degraded" />
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </SectionCard>

      {selfTestMutation.data ? (
        <SectionCard title="Latest self-test" subtitle="Lightweight worker diagnostics against binaries, scratch, DB, and local service wiring.">
          <div className="card-stack">
            <div className="info-strip">
              <StatusBadge value={selfTestMutation.data.status} />
              <span>{selfTestMutation.data.summary}</span>
            </div>
            <div className="metric-grid">
              <HealthMetric label="Started" value={formatDateTime(selfTestMutation.data.started_at)} />
              <HealthMetric label="Completed" value={formatDateTime(selfTestMutation.data.completed_at)} />
            </div>
            <div className="list-stack">
              {selfTestMutation.data.checks.map((check) => (
                <div key={check.code} className="list-row">
                  <div>
                    <strong>{check.code.replace(/_/g, " ")}</strong>
                    <p>{check.message}</p>
                  </div>
                  <StatusBadge value={check.status} />
                </div>
              ))}
            </div>
          </div>
        </SectionCard>
      ) : null}
    </div>
  );
}

function BinaryCard({
  title,
  item,
}: {
  title: string;
  item: {
    configured_path: string;
    status: string;
    discoverable: boolean;
    message: string;
  };
}) {
  return (
    <article className="status-card">
      <div className="badge-row">
        <StatusBadge value={item.status} />
        <strong>{title}</strong>
      </div>
      <p className="muted-copy">{item.configured_path}</p>
      <p className="muted-copy">{item.message}</p>
      <HealthMetric label="Discoverable" value={formatRelativeBoolean(item.discoverable)} />
    </article>
  );
}

function QueueHealthCard({
  workerStatus,
}: {
  workerStatus: {
    queue_health: {
      status: string;
      summary: string;
      pending_count: number;
      running_count: number;
      failed_count: number;
      manual_review_count: number;
      completed_count: number;
      oldest_pending_age_seconds: number | null;
      last_completed_age_seconds: number | null;
      recent_failed_count: number;
      recent_manual_review_count: number;
    };
    last_run_completed_at: string | null;
    last_result_status: string | null;
    last_failure_message: string | null;
  };
}) {
  const { queue_health: queue } = workerStatus;

  return (
    <div className="card-stack">
      <div className="info-strip">
        <StatusBadge value={queue.status} />
        <span>{queue.summary}</span>
      </div>
      <div className="metric-grid">
        <HealthMetric label="Pending" value={String(queue.pending_count)} />
        <HealthMetric label="Running" value={String(queue.running_count)} />
        <HealthMetric label="Failed" value={String(queue.failed_count)} />
        <HealthMetric label="Manual review" value={String(queue.manual_review_count)} />
        <HealthMetric label="Completed" value={String(queue.completed_count)} />
        <HealthMetric label="Oldest pending age" value={formatDurationSeconds(queue.oldest_pending_age_seconds)} />
        <HealthMetric label="Last completed age" value={formatDurationSeconds(queue.last_completed_age_seconds)} />
        <HealthMetric label="Recent failures" value={String(queue.recent_failed_count)} />
      </div>
      <p className="muted-copy">
        Last worker result: <strong>{workerStatus.last_result_status ?? "Not available"}</strong> ·{" "}
        {formatDateTime(workerStatus.last_run_completed_at)}
      </p>
      {workerStatus.last_failure_message ? <p className="muted-copy">{workerStatus.last_failure_message}</p> : null}
    </div>
  );
}

function HealthMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="metric-panel">
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function HealthStatCard({
  label,
  status,
  value,
}: {
  label: string;
  status: string | undefined;
  value: string | number;
}) {
  return (
    <article className="stat-card">
      <span className="stat-label">{label}</span>
      <strong className="stat-value health-stat-value">{value}</strong>
      <StatusBadge value={status} />
    </article>
  );
}
