import { Link, useParams } from "react-router-dom";
import { useMemo, useState } from "react";

import { DataTable } from "../../components/DataTable";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { PathActionForm } from "../../components/PathActionForm";
import { PayloadViewer } from "../../components/PayloadViewer";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useCreateJobMutation, useFileDetailQuery, useFilesQuery, useLatestPlanQuery, useLatestProbeQuery, usePlanFileMutation, useProbeFileMutation } from "../../lib/api/hooks";
import { formatBytes, formatDateTime, formatRelativeBoolean } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

export function FilesPage() {
  const { fileId } = useParams();
  const [lifecycleState, setLifecycleState] = useState("");
  const [complianceState, setComplianceState] = useState("");
  const [pathSearch, setPathSearch] = useState("");
  const [protectedOnly, setProtectedOnly] = useState("");
  const [is4k, setIs4k] = useState("");

  const filters = useMemo(
    () => ({
      lifecycle_state: lifecycleState || undefined,
      compliance_state: complianceState || undefined,
      path_search: pathSearch || undefined,
      protected_only: protectedOnly === "" ? undefined : protectedOnly === "true",
      is_4k: is4k === "" ? undefined : is4k === "true",
      limit: 100,
    }),
    [complianceState, is4k, lifecycleState, pathSearch, protectedOnly],
  );

  const filesQuery = useFilesQuery(filters);
  const detailQuery = useFileDetailQuery(fileId);
  const latestProbeQuery = useLatestProbeQuery(detailQuery.data?.latest_probe_snapshot_id ? fileId : undefined);
  const latestPlanQuery = useLatestPlanQuery(detailQuery.data?.latest_plan_snapshot_id ? fileId : undefined);
  const probeMutation = useProbeFileMutation();
  const planMutation = usePlanFileMutation();
  const createJobMutation = useCreateJobMutation();

  const queryError =
    filesQuery.error ?? detailQuery.error ?? latestProbeQuery.error ?? latestPlanQuery.error;

  if (filesQuery.isLoading) {
    return <LoadingBlock label="Loading files" />;
  }

  if (queryError instanceof Error) {
    return <ErrorPanel title="Unable to load files" message={queryError.message} />;
  }

  const files = filesQuery.data?.items ?? [];
  const detail = detailQuery.data;
  const latestProbe = latestProbeQuery.data;
  const latestPlan = latestPlanQuery.data;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Files"
        title="Tracked files"
        description="Inspect tracked files, filter by current state, and trigger probe or plan tasks by source path."
      />

      {probeMutation.error instanceof Error ? (
        <ErrorPanel title="Probe request failed" message={probeMutation.error.message} />
      ) : null}
      {planMutation.error instanceof Error ? (
        <ErrorPanel title="Plan request failed" message={planMutation.error.message} />
      ) : null}
      {createJobMutation.error instanceof Error ? (
        <ErrorPanel title="Job creation failed" message={createJobMutation.error.message} />
      ) : null}

      <section className="dashboard-grid">
        <SectionCard title="Probe or plan" subtitle="Submit explicit operator actions by source path.">
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
          </div>
        </SectionCard>

        <SectionCard title="Filters" subtitle="Narrow the list using current file state.">
          <div className="filter-grid">
            <label className="field">
              <span>Lifecycle state</span>
              <input value={lifecycleState} onChange={(event) => setLifecycleState(event.target.value)} placeholder="queued" />
            </label>
            <label className="field">
              <span>Compliance state</span>
              <input value={complianceState} onChange={(event) => setComplianceState(event.target.value)} placeholder="compliant" />
            </label>
            <label className="field">
              <span>Path search</span>
              <input value={pathSearch} onChange={(event) => setPathSearch(event.target.value)} placeholder="Example Film" />
            </label>
            <label className="field">
              <span>Protected</span>
              <select value={protectedOnly} onChange={(event) => setProtectedOnly(event.target.value)}>
                <option value="">Any</option>
                <option value="true">Protected only</option>
                <option value="false">Unprotected only</option>
              </select>
            </label>
            <label className="field">
              <span>4K</span>
              <select value={is4k} onChange={(event) => setIs4k(event.target.value)}>
                <option value="">Any</option>
                <option value="true">4K only</option>
                <option value="false">Non-4K only</option>
              </select>
            </label>
          </div>
        </SectionCard>
      </section>

      <section className="two-column-layout">
        <SectionCard title="Tracked files" subtitle={`${files.length} result${files.length === 1 ? "" : "s"}`}>
          <DataTable
            items={files}
            rowKey={(item) => item.id}
            empty={<EmptyState title="No tracked files" message="Use probe or plan to create the first tracked file records." />}
            columns={[
              {
                key: "file",
                header: "File",
                render: (item) => (
                  <Link className="table-link" to={APP_ROUTES.fileDetail(item.id)}>
                    <strong>{item.source_filename}</strong>
                    <span>{item.source_directory}</span>
                    {item.requires_review ? (
                      <span className="badge-row">
                        <StatusBadge value={item.review_status ?? "open"} />
                        <span>Open in Manual Review</span>
                      </span>
                    ) : null}
                  </Link>
                ),
              },
              {
                key: "lifecycle",
                header: "Lifecycle",
                render: (item) => <StatusBadge value={item.lifecycle_state} />,
              },
              {
                key: "compliance",
                header: "Compliance",
                render: (item) => <StatusBadge value={item.compliance_state} />,
              },
              {
                key: "protection",
                header: "Protected",
                render: (item) => (item.is_protected ? "Yes" : "No"),
              },
              {
                key: "updated",
                header: "Updated",
                render: (item) => formatDateTime(item.updated_at),
              },
            ]}
          />
        </SectionCard>

        <SectionCard
          title="File detail"
          subtitle={detail ? detail.source_filename : "Select a file to inspect its latest probe and plan state."}
          actions={
            detail ? (
              <button
                className="button button-primary button-small"
                type="button"
                onClick={() => createJobMutation.mutate({ tracked_file_id: detail.id })}
                disabled={createJobMutation.isPending}
              >
                {createJobMutation.isPending ? "Creating…" : "Create job from latest plan"}
              </button>
            ) : null
          }
        >
          {fileId && detailQuery.isLoading ? (
            <LoadingBlock label="Loading file detail" />
          ) : detail ? (
            <div className="card-stack">
              <KeyValueList
                items={[
                  { label: "Source path", value: detail.source_path },
                  { label: "Lifecycle state", value: <StatusBadge value={detail.lifecycle_state} /> },
                  { label: "Compliance state", value: <StatusBadge value={detail.compliance_state} /> },
                  { label: "Protected", value: formatRelativeBoolean(detail.is_protected) },
                  { label: "Protected source", value: detail.protected_source ?? "None" },
                  { label: "Manual review", value: detail.requires_review ? <Link to={APP_ROUTES.reviewDetail(detail.id)}><StatusBadge value={detail.review_status ?? "open"} /></Link> : "Not required" },
                  { label: "4K", value: formatRelativeBoolean(detail.is_4k) },
                  { label: "Last observed size", value: formatBytes(detail.last_observed_size) },
                  { label: "Updated", value: formatDateTime(detail.updated_at) },
                ]}
              />
              {latestPlan ? (
                <SectionCard title="Latest plan" subtitle={`Action: ${latestPlan.action}`}>
                  <KeyValueList
                    items={[
                      { label: "Action", value: <StatusBadge value={latestPlan.action} /> },
                      { label: "Confidence", value: <StatusBadge value={latestPlan.confidence} /> },
                      { label: "Policy version", value: latestPlan.policy_version },
                      { label: "Profile", value: latestPlan.profile_name ?? "Default policy" },
                    ]}
                  />
                  <PayloadViewer payload={latestPlan.payload} />
                </SectionCard>
              ) : null}
              {latestProbe ? (
                <SectionCard title="Latest probe" subtitle={latestProbe.format_name ?? "Probe snapshot"}>
                  <KeyValueList
                    items={[
                      { label: "Video streams", value: latestProbe.video_stream_count },
                      { label: "Audio streams", value: latestProbe.audio_stream_count },
                      { label: "Subtitle streams", value: latestProbe.subtitle_stream_count },
                      { label: "4K", value: formatRelativeBoolean(latestProbe.is_4k) },
                    ]}
                  />
                  <PayloadViewer payload={latestProbe.payload} />
                </SectionCard>
              ) : null}
            </div>
          ) : (
            <EmptyState title="No file selected" message="Choose a file from the list to inspect its latest snapshots." />
          )}
        </SectionCard>
      </section>
    </div>
  );
}
