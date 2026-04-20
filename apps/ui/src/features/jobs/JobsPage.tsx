import { Link, useParams } from "react-router-dom";
import { useMemo, useState } from "react";

import { DataTable } from "../../components/DataTable";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useCreateJobMutation, useJobDetailQuery, useJobsQuery, useRetryJobMutation, useRunWorkerOnceMutation } from "../../lib/api/hooks";
import { formatDateTime } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

export function JobsPage() {
  const { jobId } = useParams();
  const [status, setStatus] = useState("");
  const [fileId, setFileId] = useState("");
  const [createFromFileId, setCreateFromFileId] = useState("");

  const filters = useMemo(
    () => ({
      status: status || undefined,
      file_id: fileId || undefined,
      limit: 100,
    }),
    [fileId, status],
  );

  const jobsQuery = useJobsQuery(filters);
  const detailQuery = useJobDetailQuery(jobId);
  const retryMutation = useRetryJobMutation();
  const createJobMutation = useCreateJobMutation();
  const runOnceMutation = useRunWorkerOnceMutation();

  const error = jobsQuery.error ?? detailQuery.error;
  if (jobsQuery.isLoading) {
    return <LoadingBlock label="Loading jobs" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load jobs" message={error.message} />;
  }

  const jobs = jobsQuery.data?.items ?? [];
  const detail = detailQuery.data;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Jobs"
        title="Job queue"
        description="Review the persisted job history, retry eligible jobs, create jobs from file ids, and trigger one local worker pass."
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

      {retryMutation.error instanceof Error ? (
        <ErrorPanel title="Retry failed" message={retryMutation.error.message} />
      ) : null}
      {createJobMutation.error instanceof Error ? (
        <ErrorPanel title="Job creation failed" message={createJobMutation.error.message} />
      ) : null}
      {runOnceMutation.error instanceof Error ? (
        <ErrorPanel title="Worker run failed" message={runOnceMutation.error.message} />
      ) : null}

      <section className="dashboard-grid">
        <SectionCard title="Filters" subtitle="Narrow the jobs list using current API filters.">
          <div className="filter-grid">
            <label className="field">
              <span>Status</span>
              <input value={status} onChange={(event) => setStatus(event.target.value)} placeholder="failed" />
            </label>
            <label className="field">
              <span>File id</span>
              <input value={fileId} onChange={(event) => setFileId(event.target.value)} placeholder="Tracked file id" />
            </label>
          </div>
        </SectionCard>
        <SectionCard title="Create job" subtitle="Create a pending job from the latest plan for a tracked file.">
          <form
            className="inline-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (!createFromFileId.trim()) {
                return;
              }
              createJobMutation.mutate({ tracked_file_id: createFromFileId.trim() });
            }}
          >
            <label className="field field-inline">
              <span>Tracked file id</span>
              <input
                value={createFromFileId}
                onChange={(event) => setCreateFromFileId(event.target.value)}
                placeholder="Enter a tracked file id"
              />
            </label>
            <button className="button button-secondary" type="submit" disabled={createJobMutation.isPending}>
              {createJobMutation.isPending ? "Creating…" : "Create job"}
            </button>
          </form>
        </SectionCard>
      </section>

      <section className="two-column-layout">
        <SectionCard title="Jobs" subtitle={`${jobs.length} result${jobs.length === 1 ? "" : "s"}`}>
          <DataTable
            items={jobs}
            rowKey={(item) => item.id}
            empty={<EmptyState title="No jobs found" message="Create a plan, then create a job to populate the queue." />}
            columns={[
              {
                key: "job",
                header: "Job",
                render: (item) => (
                  <Link className="table-link" to={APP_ROUTES.jobDetail(item.id)}>
                    <strong>{item.id.slice(0, 8)}</strong>
                    <span>File {item.tracked_file_id.slice(0, 8)}</span>
                  </Link>
                ),
              },
              {
                key: "status",
                header: "Status",
                render: (item) => <StatusBadge value={item.status} />,
              },
              {
                key: "verification",
                header: "Verification",
                render: (item) => <StatusBadge value={item.verification_status} />,
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
          title="Job detail"
          subtitle={detail ? `Job ${detail.id}` : "Select a job to inspect execution, verification, and replacement state."}
          actions={
            detail &&
            ["failed", "manual_review", "skipped"].includes(detail.status) ? (
              <button
                className="button button-primary button-small"
                type="button"
                onClick={() => retryMutation.mutate(detail.id)}
                disabled={retryMutation.isPending}
              >
                {retryMutation.isPending ? "Retrying…" : "Retry job"}
              </button>
            ) : null
          }
        >
          {jobId && detailQuery.isLoading ? (
            <LoadingBlock label="Loading job detail" />
          ) : detail ? (
            <div className="card-stack">
              <KeyValueList
                items={[
                  { label: "Status", value: <StatusBadge value={detail.status} /> },
                  { label: "Verification", value: <StatusBadge value={detail.verification_status} /> },
                  { label: "Replacement", value: <StatusBadge value={detail.replacement_status} /> },
                  { label: "Started", value: formatDateTime(detail.started_at) },
                  { label: "Completed", value: formatDateTime(detail.completed_at) },
                  { label: "Failure message", value: detail.failure_message ?? "Not available" },
                ]}
              />
              {detail.execution_command ? (
                <SectionCard title="Execution command" subtitle="Recorded command list from the worker run.">
                  <pre>{detail.execution_command.join(" ")}</pre>
                </SectionCard>
              ) : null}
              {detail.verification_payload ? (
                <SectionCard title="Verification summary" subtitle="Structured verification outcome.">
                  <pre>{JSON.stringify(detail.verification_payload, null, 2)}</pre>
                </SectionCard>
              ) : null}
              {detail.replacement_payload ? (
                <SectionCard title="Replacement summary" subtitle="Structured final-placement outcome.">
                  <pre>{JSON.stringify(detail.replacement_payload, null, 2)}</pre>
                </SectionCard>
              ) : null}
            </div>
          ) : (
            <EmptyState title="No job selected" message="Choose a job from the list to inspect the latest execution result." />
          )}
        </SectionCard>
      </section>
    </div>
  );
}
