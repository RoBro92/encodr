import { Link, useParams } from "react-router-dom";

import { DataTable } from "../../components/DataTable";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useDisableWorkerMutation,
  useEnableWorkerMutation,
  useWorkerDetailQuery,
  useWorkersQuery,
} from "../../lib/api/hooks";
import { formatDateTime, formatRelativeBoolean } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

export function WorkersPage() {
  const { workerId } = useParams();
  const workersQuery = useWorkersQuery();
  const detailQuery = useWorkerDetailQuery(workerId);
  const enableMutation = useEnableWorkerMutation();
  const disableMutation = useDisableWorkerMutation();

  const error = workersQuery.error ?? detailQuery.error;
  if (workersQuery.isLoading) {
    return <LoadingBlock label="Loading workers" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load workers" message={error.message} />;
  }

  const workers = workersQuery.data?.items ?? [];
  const detail = detailQuery.data;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Workers"
        title="Worker inventory"
        description="Inspect local and remote worker identity, health, capabilities, and future assignment readiness."
      />

      {enableMutation.error instanceof Error ? (
        <ErrorPanel title="Enable worker failed" message={enableMutation.error.message} />
      ) : null}
      {disableMutation.error instanceof Error ? (
        <ErrorPanel title="Disable worker failed" message={disableMutation.error.message} />
      ) : null}

      <section className="two-column-layout">
        <SectionCard title="Workers" subtitle={`${workers.length} result${workers.length === 1 ? "" : "s"}`}>
          <DataTable
            items={workers}
            rowKey={(item) => item.id}
            empty={<EmptyState title="No workers found" message="The local worker and any registered remote workers will appear here." />}
            columns={[
              {
                key: "worker",
                header: "Worker",
                render: (item) => (
                  <Link className="table-link" to={APP_ROUTES.workerDetail(item.id)}>
                    <strong>{item.display_name}</strong>
                    <span>{item.worker_key}</span>
                  </Link>
                ),
              },
              {
                key: "type",
                header: "Type",
                render: (item) => <StatusBadge value={item.worker_type} />,
              },
              {
                key: "health",
                header: "Health",
                render: (item) => <StatusBadge value={item.health_status} />,
              },
              {
                key: "enabled",
                header: "Enabled",
                render: (item) => formatRelativeBoolean(item.enabled),
              },
              {
                key: "seen",
                header: "Last seen",
                render: (item) => formatDateTime(item.last_seen_at),
              },
            ]}
          />
        </SectionCard>

        <SectionCard
          title="Worker detail"
          subtitle={detail ? detail.display_name : "Select a worker to inspect detailed capability and runtime state."}
          actions={
            detail && detail.worker_type === "remote" ? (
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
            ) : null
          }
        >
          {workerId && detailQuery.isLoading ? (
            <LoadingBlock label="Loading worker detail" />
          ) : detail ? (
            <div className="card-stack">
              <KeyValueList
                items={[
                  { label: "Worker key", value: detail.worker_key },
                  { label: "Type", value: <StatusBadge value={detail.worker_type} /> },
                  { label: "Registration", value: <StatusBadge value={detail.registration_status} /> },
                  { label: "Health", value: <StatusBadge value={detail.health_status} /> },
                  { label: "Enabled", value: formatRelativeBoolean(detail.enabled) },
                  { label: "Last heartbeat", value: formatDateTime(detail.last_heartbeat_at) },
                  { label: "Last seen", value: formatDateTime(detail.last_seen_at) },
                  { label: "Host", value: detail.host_summary.hostname ?? "Not reported" },
                  { label: "Platform", value: detail.host_summary.platform ?? "Not reported" },
                  { label: "Agent version", value: detail.host_summary.agent_version ?? "Not reported" },
                ]}
              />

              <SectionCard title="Capabilities" subtitle="Explicit worker capability declarations for future routing.">
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

              <SectionCard title="Runtime summary" subtitle="Current heartbeat and runtime metadata from the worker.">
                <KeyValueList
                  items={[
                    { label: "Queue", value: detail.runtime_summary?.queue ?? "Not reported" },
                    { label: "Scratch dir", value: detail.runtime_summary?.scratch_dir ?? "Not reported" },
                    { label: "Media mounts", value: detail.runtime_summary?.media_mounts.join(", ") || "None reported" },
                    { label: "Pending assignments", value: String(detail.pending_assignment_count) },
                    { label: "Last completed job", value: detail.last_completed_job_id ?? detail.last_processed_job_id ?? "Not reported" },
                  ]}
                />
              </SectionCard>

              <SectionCard title="Binary summary" subtitle="Worker-reported binary metadata where available.">
                {detail.binary_summary.length > 0 ? (
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
                ) : (
                  <EmptyState title="No binary summary" message="This worker has not reported binary metadata yet." />
                )}
              </SectionCard>
            </div>
          ) : (
            <EmptyState title="No worker selected" message="Choose a worker from the list to inspect its detailed health and capability summary." />
          )}
        </SectionCard>
      </section>
    </div>
  );
}
