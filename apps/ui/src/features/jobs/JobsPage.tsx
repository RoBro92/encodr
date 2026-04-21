import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useCreateJobMutation, useFilesQuery, useJobDetailQuery, useJobsQuery, useRetryJobMutation, useRunWorkerOnceMutation } from "../../lib/api/hooks";
import type { FileSummary } from "../../lib/types/api";
import { formatDateTime } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

const JOB_STATUS_OPTIONS = [
  { label: "Any status", value: "" },
  { label: "Pending", value: "pending" },
  { label: "Running", value: "running" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
  { label: "Manual review", value: "manual_review" },
  { label: "Skipped", value: "skipped" },
];

export function JobsPage() {
  const { jobId } = useParams();
  const [status, setStatus] = useState("");
  const [fileId, setFileId] = useState("");
  const [fileSearch, setFileSearch] = useState("");
  const [createFromFileId, setCreateFromFileId] = useState("");
  const [createFileSearch, setCreateFileSearch] = useState("");

  const filters = useMemo(
    () => ({
      status: status || undefined,
      file_id: fileId || undefined,
      limit: 100,
    }),
    [fileId, status],
  );

  const filterFilesQuery = useFilesQuery({
    path_search: fileSearch.trim() || undefined,
    limit: 25,
  });
  const createFilesQuery = useFilesQuery({
    path_search: createFileSearch.trim() || undefined,
    limit: 25,
  });
  const jobsQuery = useJobsQuery(filters);
  const detailQuery = useJobDetailQuery(jobId);
  const retryMutation = useRetryJobMutation();
  const createJobMutation = useCreateJobMutation();
  const runOnceMutation = useRunWorkerOnceMutation();

  const error = filterFilesQuery.error ?? createFilesQuery.error ?? jobsQuery.error ?? detailQuery.error;
  if (jobsQuery.isLoading || filterFilesQuery.isLoading || createFilesQuery.isLoading) {
    return <LoadingBlock label="Loading jobs" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load jobs" message={error.message} />;
  }

  const filterFiles = filterFilesQuery.data?.items ?? [];
  const createFiles = createFilesQuery.data?.items ?? [];
  const files = deduplicateTrackedFiles([...filterFiles, ...createFiles]);
  const jobs = jobsQuery.data?.items ?? [];
  const detail = detailQuery.data;
  const metrics = summariseJobs(jobs);
  const canRetry = detail ? ["failed", "manual_review", "skipped"].includes(detail.status) : false;
  const selectedJobId = detail?.id;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Jobs"
        title="Jobs"
        description="Monitor the queue, inspect outcomes, and retry jobs that need another pass."
        actions={
          <div className="action-group">
            <button
              className="button button-primary"
              type="button"
              onClick={() => runOnceMutation.mutate()}
              disabled={runOnceMutation.isPending}
            >
              {runOnceMutation.isPending ? "Running worker…" : "Run worker once"}
            </button>
            <span className="action-helper">Process the next queued job.</span>
          </div>
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

      <section className="metric-grid metric-grid-compact">
        <div className="metric-panel">
          <span className="metric-label">Visible jobs</span>
          <strong>{metrics.total}</strong>
        </div>
        <div className="metric-panel">
          <span className="metric-label">Active</span>
          <strong>{metrics.active}</strong>
        </div>
        <div className="metric-panel">
          <span className="metric-label">Needs attention</span>
          <strong>{metrics.attention}</strong>
        </div>
        <div className="metric-panel">
          <span className="metric-label">Completed</span>
          <strong>{metrics.completed}</strong>
        </div>
      </section>

      <SectionCard title="Queue controls" subtitle="Filter the queue or create a job from a tracked file.">
        <div className="jobs-toolbar">
          <label className="field">
            <span>Status</span>
            <select aria-label="Status" value={status} onChange={(event) => setStatus(event.target.value)}>
              {JOB_STATUS_OPTIONS.map((option) => (
                <option key={option.value || "any"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <TrackedFilePicker
            label="Tracked file"
            items={files}
            selectedId={fileId}
            query={fileSearch}
            placeholder="Filter by tracked file"
            onQueryChange={(value) => {
              setFileSearch(value);
              if (!value) {
                setFileId("");
              }
            }}
            onSelectedIdChange={(value, label) => {
              setFileId(value);
              setFileSearch(label);
            }}
            onClear={() => {
              setFileId("");
              setFileSearch("");
            }}
          />

          <form
            className="jobs-create-inline"
            onSubmit={(event) => {
              event.preventDefault();
              if (!createFromFileId.trim()) {
                return;
              }
              createJobMutation.mutate({ tracked_file_id: createFromFileId.trim() });
            }}
          >
            <TrackedFilePicker
              label="Create from tracked file"
              items={files}
              selectedId={createFromFileId}
              query={createFileSearch}
              placeholder="Choose a tracked file"
              onQueryChange={(value) => {
                setCreateFileSearch(value);
                if (!value) {
                  setCreateFromFileId("");
                }
              }}
              onSelectedIdChange={(value, label) => {
                setCreateFromFileId(value);
                setCreateFileSearch(label);
              }}
              onClear={() => {
                setCreateFromFileId("");
                setCreateFileSearch("");
              }}
            />
            <button className="button button-secondary" type="submit" disabled={createJobMutation.isPending || !createFromFileId}>
              {createJobMutation.isPending ? "Creating…" : "Create job"}
            </button>
          </form>
        </div>
      </SectionCard>

      <section className={`jobs-review-layout${detail || (jobId && detailQuery.isLoading) ? "" : " jobs-review-layout-single"}`}>
        <SectionCard title="Queue" subtitle={`${jobs.length} job${jobs.length === 1 ? "" : "s"} in view`}>
          {jobs.length === 0 ? (
            <EmptyState title="No jobs yet" message="Create a plan in Library, then create a job to populate the queue." />
          ) : (
            <div className="record-list" role="list" aria-label="Jobs list">
              {jobs.map((item) => {
                const isActive = item.id === jobId;
                return (
                  <Link
                    key={item.id}
                    className={`record-list-item${isActive ? " record-list-item-active" : ""}`}
                    to={APP_ROUTES.jobDetail(item.id)}
                  >
                    <div className="record-list-main">
                      <div className="record-list-heading">
                        <strong>{shortId(item.id)}</strong>
                        <span>{jobFileLabel(item, files)}</span>
                      </div>
                      <div className="badge-row">
                        <StatusBadge value={item.status} />
                        {item.requires_review ? <StatusBadge value={item.review_status ?? "open"} /> : null}
                        {item.tracked_file_is_protected ? <StatusBadge value="protected" /> : null}
                      </div>
                    </div>
                    <div className="record-list-meta">
                      <span className="record-list-kicker">{jobOutcomeLabel(item)}</span>
                      <span>{formatDateTime(item.updated_at)}</span>
                      {item.failure_message ? (
                        <span className="record-list-emphasis">{truncate(item.failure_message, 84)}</span>
                      ) : item.status === "completed" ? (
                        <span className="record-list-emphasis">{replacementSummary(item)}</span>
                      ) : null}
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </SectionCard>

        {jobId && detailQuery.isLoading ? (
          <SectionCard title="Selected job" subtitle="Loading the latest result.">
            <LoadingBlock label="Loading job detail" />
          </SectionCard>
        ) : detail ? (
          <SectionCard
            title="Selected job"
            subtitle={jobFileLabel(detail, files)}
            actions={
              canRetry ? (
                <button
                  className="button button-primary button-small"
                  type="button"
                  onClick={() => {
                    if (selectedJobId) {
                      retryMutation.mutate(selectedJobId);
                    }
                  }}
                  disabled={retryMutation.isPending}
                >
                  {retryMutation.isPending ? "Retrying…" : "Retry job"}
                </button>
              ) : null
            }
          >
            <div className="card-stack">
              <div className="badge-row">
                <StatusBadge value={detail.status} />
                <StatusBadge value={detail.verification_status} />
                <StatusBadge value={detail.replacement_status} />
                {detail.requires_review ? <StatusBadge value={detail.review_status ?? "open"} /> : null}
                {detail.tracked_file_is_protected ? <StatusBadge value="protected" /> : null}
              </div>

              {detail.failure_message ? (
                <div className="info-strip info-strip-danger">
                  <strong>Failure</strong>
                  <span>{detail.failure_message}</span>
                </div>
              ) : null}

              <section className="metric-grid metric-grid-compact">
                <div className="metric-pill">
                  <span className="metric-label">Worker</span>
                  <strong>{detail.worker_name ?? "Not assigned"}</strong>
                </div>
                <div className="metric-pill">
                  <span className="metric-label">Attempts</span>
                  <strong>{detail.attempt_count}</strong>
                </div>
                <div className="metric-pill">
                  <span className="metric-label">Updated</span>
                  <strong>{formatDateTime(detail.updated_at)}</strong>
                </div>
              </section>

              <KeyValueList
                items={[
                  { label: "Tracked file", value: detail.tracked_file_id },
                  {
                    label: "Review state",
                    value: detail.requires_review ? (
                      <Link className="text-link" to={APP_ROUTES.reviewDetail(detail.tracked_file_id)}>
                        {detail.review_status ?? "open"}
                      </Link>
                    ) : (
                      "No review required"
                    ),
                  },
                  {
                    label: "Protected file",
                    value: detail.tracked_file_is_protected ? (
                      <Link className="text-link" to={APP_ROUTES.reviewDetail(detail.tracked_file_id)}>
                        View review item
                      </Link>
                    ) : (
                      "No"
                    ),
                  },
                  { label: "Started", value: formatDateTime(detail.started_at) },
                  { label: "Completed", value: formatDateTime(detail.completed_at) },
                  { label: "Output path", value: detail.final_output_path ?? detail.output_path ?? "Not written yet" },
                ]}
              />

              <CollapsibleSection
                title="Advanced execution details"
                subtitle="Command, output streams, and worker stderr/stdout."
              >
                <KeyValueList
                  items={[
                    { label: "Command", value: detail.execution_command ? <pre>{detail.execution_command.join(" ")}</pre> : "Not recorded" },
                    { label: "Stdout", value: detail.execution_stdout ? <pre>{detail.execution_stdout}</pre> : "Not recorded" },
                    { label: "Stderr", value: detail.execution_stderr ? <pre>{detail.execution_stderr}</pre> : "Not recorded" },
                  ]}
                />
              </CollapsibleSection>

              <CollapsibleSection
                title="Advanced verification details"
                subtitle="Verification rules and recorded verification payload."
              >
                <KeyValueList
                  items={[
                    { label: "Require verification", value: detail.require_verification ? "Yes" : "No" },
                    { label: "Keep original until verified", value: detail.keep_original_until_verified ? "Yes" : "No" },
                    { label: "Verification payload", value: detail.verification_payload ? <pre>{JSON.stringify(detail.verification_payload, null, 2)}</pre> : "Not recorded" },
                  ]}
                />
              </CollapsibleSection>

              <CollapsibleSection
                title="Advanced replacement details"
                subtitle="Final placement, backup handling, and replacement payload."
              >
                <KeyValueList
                  items={[
                    { label: "Replace in place", value: detail.replace_in_place ? "Yes" : "No" },
                    { label: "Delete replaced source", value: detail.delete_replaced_source ? "Yes" : "No" },
                    { label: "Backup path", value: detail.original_backup_path ?? "Not created" },
                    { label: "Replacement failure", value: detail.replacement_failure_message ?? "None" },
                    { label: "Replacement payload", value: detail.replacement_payload ? <pre>{JSON.stringify(detail.replacement_payload, null, 2)}</pre> : "Not recorded" },
                  ]}
                />
              </CollapsibleSection>
            </div>
          </SectionCard>
        ) : null}
      </section>
    </div>
  );
}

function TrackedFilePicker({
  label,
  items,
  selectedId,
  query,
  placeholder,
  onQueryChange,
  onSelectedIdChange,
  onClear,
}: {
  label: string;
  items: FileSummary[];
  selectedId: string;
  query: string;
  placeholder: string;
  onQueryChange: (value: string) => void;
  onSelectedIdChange: (value: string, label: string) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const matches = useMemo(() => {
    const search = query.trim().toLowerCase();
    if (!search) {
      return items.slice(0, 8);
    }
    return items
      .filter((item) => {
        const label = formatTrackedFileOption(item).toLowerCase();
        return (
          label.includes(search) ||
          item.id.toLowerCase().includes(search) ||
          item.source_path.toLowerCase().includes(search)
        );
      })
      .slice(0, 8);
  }, [items, query]);

  return (
    <label className="field file-search-field">
      <span>{label}</span>
      <div className="combobox">
        <input
          aria-label={label}
          value={query}
          placeholder={placeholder}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            window.setTimeout(() => setOpen(false), 120);
          }}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        {selectedId ? (
          <button className="button button-secondary button-small" type="button" onClick={onClear}>
            Clear
          </button>
        ) : null}
        {open && matches.length > 0 ? (
          <div className="combobox-menu" role="listbox" aria-label={`${label} options`}>
            {matches.map((item) => {
              const optionLabel = formatTrackedFileOption(item);
              return (
                <button
                  key={item.id}
                  className={`combobox-option${item.id === selectedId ? " combobox-option-active" : ""}`}
                  type="button"
                  role="option"
                  aria-selected={item.id === selectedId}
                  onMouseDown={(event) => {
                    event.preventDefault();
                  }}
                  onClick={() => {
                    onSelectedIdChange(item.id, optionLabel);
                    setOpen(false);
                  }}
                >
                  <strong>{item.source_filename}</strong>
                  <span>{item.source_directory}</span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </label>
  );
}

function deduplicateTrackedFiles(items: FileSummary[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) {
      return false;
    }
    seen.add(item.id);
    return true;
  });
}

function formatTrackedFileOption(file: FileSummary) {
  return `${file.source_filename} — ${file.source_directory}`;
}

function jobFileLabel(
  job: {
    tracked_file_id: string;
  },
  files: FileSummary[],
) {
  const trackedFile = files.find((item) => item.id === job.tracked_file_id);
  return trackedFile ? trackedFile.source_filename : `Tracked file ${shortId(job.tracked_file_id)}`;
}

function replacementSummary(job: {
  replacement_status: string;
  verification_status: string;
}) {
  if (job.replacement_status === "succeeded") {
    return "Replacement succeeded";
  }
  if (job.verification_status === "passed") {
    return "Verification passed";
  }
  return "Completed";
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function truncate(value: string, max: number) {
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max - 1)}…`;
}

function summariseJobs(
  jobs: Array<{
    status: string;
    requires_review: boolean;
    tracked_file_is_protected: boolean | null;
  }>,
) {
  return {
    total: jobs.length,
    active: jobs.filter((job) => ["pending", "running"].includes(job.status)).length,
    attention: jobs.filter(
      (job) =>
        ["failed", "manual_review", "skipped"].includes(job.status) ||
        job.requires_review ||
        Boolean(job.tracked_file_is_protected),
    ).length,
    completed: jobs.filter((job) => job.status === "completed").length,
  };
}

function jobOutcomeLabel(job: {
  status: string;
  failure_message: string | null;
  requires_review: boolean;
  tracked_file_is_protected: boolean | null;
}) {
  if (job.failure_message) {
    return "Failed";
  }
  if (job.tracked_file_is_protected) {
    return "Protected file";
  }
  if (job.requires_review || job.status === "manual_review") {
    return "Needs review";
  }
  if (job.status === "completed") {
    return "Completed";
  }
  if (job.status === "running") {
    return "Running";
  }
  return "In queue";
}
