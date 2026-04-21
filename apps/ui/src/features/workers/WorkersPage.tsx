import { Link, useParams } from "react-router-dom";

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

  const workers = (workersQuery.data?.items ?? []).map((item) => ({
    ...item,
    displayHealthStatus:
      item.worker_type === "remote" && !item.last_heartbeat_at ? "not_configured" : item.health_status,
    displayHealthSummary:
      item.worker_type === "remote" && !item.last_heartbeat_at
        ? "Remote worker has not reported a heartbeat yet."
        : item.health_summary ?? "No health summary reported.",
  }));
  const detail = detailQuery.data
    ? {
        ...detailQuery.data,
        displayHealthStatus:
          detailQuery.data.worker_type === "remote" && !detailQuery.data.last_heartbeat_at
            ? "not_configured"
            : detailQuery.data.health_status,
      }
    : null;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Workers"
        title="Workers"
        description="Check worker health, availability, and readiness."
      />

      {enableMutation.error instanceof Error ? (
        <ErrorPanel title="Enable worker failed" message={enableMutation.error.message} />
      ) : null}
      {disableMutation.error instanceof Error ? (
        <ErrorPanel title="Disable worker failed" message={disableMutation.error.message} />
      ) : null}

      <section className={`jobs-review-layout${detail || (workerId && detailQuery.isLoading) ? "" : " jobs-review-layout-single"}`}>
        <SectionCard title="Workers" subtitle={`${workers.length} worker${workers.length === 1 ? "" : "s"} in view`}>
          {workers.length === 0 ? (
            <EmptyState title="No workers yet" message="Workers appear here when Encodr detects or registers them." />
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
                        <StatusBadge value={item.displayHealthStatus} />
                        <StatusBadge value={item.enabled ? "enabled" : "disabled"} />
                      </div>
                    </div>
                    <div className="record-list-meta">
                      <span className="record-list-kicker">{item.worker_type === "local" ? "Local worker" : "Remote worker"}</span>
                      <span>{formatDateTime(item.last_seen_at)}</span>
                      <span className="record-list-emphasis">{item.displayHealthSummary}</span>
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
              detail.worker_type === "remote" ? (
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
            <div className="card-stack">
              {detail.displayHealthStatus === "not_configured" ? (
                <div className="info-strip" role="note">
                  <strong>Not configured</strong>
                  <span>Remote worker setup is incomplete until Encodr receives a real heartbeat.</span>
                </div>
              ) : null}

              <KeyValueList
                items={[
                  { label: "Worker key", value: detail.worker_key },
                  { label: "Type", value: <StatusBadge value={detail.worker_type} /> },
                  { label: "Registration", value: <StatusBadge value={detail.registration_status} /> },
                  { label: "Health", value: <StatusBadge value={detail.displayHealthStatus} /> },
                  { label: "Enabled", value: formatRelativeBoolean(detail.enabled) },
                  { label: "Last heartbeat", value: formatDateTime(detail.last_heartbeat_at) },
                  { label: "Last seen", value: formatDateTime(detail.last_seen_at) },
                  { label: "Host", value: detail.host_summary.hostname ?? "Not reported" },
                  { label: "Platform", value: detail.host_summary.platform ?? "Not reported" },
                  { label: "Agent version", value: detail.host_summary.agent_version ?? "Not reported" },
                ]}
              />

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
            </div>
          </SectionCard>
        ) : null}
      </section>
    </div>
  );
}
