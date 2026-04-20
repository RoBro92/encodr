import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useRunWorkerOnceMutation, useRuntimeStatusQuery, useStorageStatusQuery, useWorkerStatusQuery } from "../../lib/api/hooks";
import { formatDateTime, formatRelativeBoolean } from "../../lib/utils/format";

export function SystemPage() {
  const workerQuery = useWorkerStatusQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();
  const runOnceMutation = useRunWorkerOnceMutation();

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

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="System"
        title="Worker and runtime status"
        description="Operational checks for the local worker, runtime dependencies, and configured storage paths."
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

      <section className="dashboard-grid">
        <SectionCard title="Worker status" subtitle="Local-only worker capability and recent run state.">
          {worker ? (
            <KeyValueList
              items={[
                { label: "Worker name", value: worker.worker_name },
                { label: "Queue", value: worker.local_worker_queue },
                { label: "FFmpeg", value: <StatusBadge value={worker.ffmpeg.discoverable ? "ok" : "failed"} /> },
                { label: "FFprobe", value: <StatusBadge value={worker.ffprobe.discoverable ? "ok" : "failed"} /> },
                { label: "Last result", value: <StatusBadge value={worker.last_result_status ?? "idle"} /> },
                { label: "Last completed run", value: formatDateTime(worker.last_run_completed_at) },
              ]}
            />
          ) : null}
        </SectionCard>

        <SectionCard title="Runtime status" subtitle="Current application and database summary.">
          {runtime ? (
            <KeyValueList
              items={[
                { label: "Version", value: runtime.version },
                { label: "Environment", value: runtime.environment },
                { label: "Database reachable", value: formatRelativeBoolean(runtime.db_reachable) },
                { label: "Auth enabled", value: formatRelativeBoolean(runtime.auth_enabled) },
                { label: "API base path", value: runtime.api_base_path },
              ]}
            />
          ) : null}
        </SectionCard>
      </section>

      <SectionCard title="Storage status" subtitle="Configured scratch, data, and media mount visibility.">
        {storage ? (
          <div className="status-grid">
            {[storage.scratch, storage.data_dir, ...storage.media_mounts].map((pathStatus) => (
              <article key={pathStatus.path} className="status-card">
                <strong>{pathStatus.path}</strong>
                <div className="badge-row">
                  <StatusBadge value={pathStatus.exists ? "ok" : "failed"} />
                  <span>{pathStatus.writable ? "Writable" : "Read-only or unavailable"}</span>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </SectionCard>
    </div>
  );
}
