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
import {
  useCreateJobMutation,
  useFilesQuery,
  useJobDetailQuery,
  useJobsQuery,
  useRetryJobMutation,
  useRunWorkerOnceMutation,
} from "../../lib/api/hooks";
import type { FileSummary, JobSummary } from "../../lib/types/api";
import { formatBytes, formatDateTime, formatDurationSeconds, titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

const JOB_STATUS_OPTIONS = [
  { label: "Any status", value: "" },
  { label: "Pending", value: "pending" },
  { label: "Scheduled", value: "scheduled" },
  { label: "Running", value: "running" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
  { label: "Interrupted", value: "interrupted" },
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
  const orderedJobs = sortJobsForDisplay(jobs);
  const detail = detailQuery.data;
  const metrics = summariseJobs(jobs);
  const canRetry = detail ? ["failed", "interrupted", "manual_review", "skipped"].includes(detail.status) : false;
  const selectedJobId = detail?.id;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Jobs"
        title="Jobs"
        description="Monitor running work, inspect outcomes, and retry jobs that need another pass."
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
          <span className="metric-label">Running now</span>
          <strong>{metrics.running}</strong>
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
              label="Create job from tracked file"
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
          {orderedJobs.length === 0 ? (
            <EmptyState title="No jobs yet" message="Create a plan in Library, then create a job to populate the queue." />
          ) : (
            <div className="record-list" role="list" aria-label="Jobs list">
              {orderedJobs.map((item) => {
                const isActive = item.id === jobId;
                return (
                  <Link
                    key={item.id}
                    className={`record-list-item${isActive ? " record-list-item-active" : ""}`}
                    to={APP_ROUTES.jobDetail(item.id)}
                  >
                    <div className="record-list-main">
                      <div className="record-list-heading">
                        <strong>{jobPrimaryLabel(item, files)}</strong>
                        <span>{jobSecondaryLabel(item)}</span>
                      </div>
                      <div className="badge-row">
                        <StatusBadge value={item.status} />
                        {item.requires_review ? <StatusBadge value={item.review_status ?? "open"} /> : null}
                        {item.tracked_file_is_protected ? <StatusBadge value="protected" /> : null}
                        {(item.actual_execution_backend ?? item.requested_execution_backend) ? (
                          <StatusBadge value={formatBackendLabel(item.actual_execution_backend ?? item.requested_execution_backend)} />
                        ) : null}
                        {item.backend_fallback_used ? <StatusBadge value="cpu fallback" /> : null}
                      </div>
                      {item.status === "running" || item.status === "pending" ? <JobProgressBar job={item} compact /> : null}
                    </div>
                    <div className="record-list-meta">
                      <span className="record-list-kicker">{jobOutcomeLabel(item)}</span>
                      <span>{item.worker_name ?? "No worker yet"}</span>
                      {(item.actual_execution_backend ?? item.requested_execution_backend) ? (
                        <span>{formatBackendLabel(item.actual_execution_backend ?? item.requested_execution_backend)}</span>
                      ) : null}
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
            subtitle={jobPrimaryLabel(detail, files)}
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

              {detail.status === "scheduled" && detail.schedule_summary ? (
                <div className="info-strip info-strip-warning">
                  <strong>Scheduled</strong>
                  <span>
                    This job is waiting for its allowed execution window.
                    {detail.scheduled_for_at ? ` Next opening: ${formatDateTime(detail.scheduled_for_at)}.` : ""}
                  </span>
                </div>
              ) : null}

              {detail.status === "interrupted" && detail.interruption_reason ? (
                <div className="info-strip info-strip-warning">
                  <strong>Interrupted</strong>
                  <span>{detail.interruption_reason}</span>
                </div>
              ) : null}

              {detail.failure_message ? (
                <div className="info-strip info-strip-danger">
                  <strong>Failure</strong>
                  <span>{detail.failure_message}</span>
                </div>
              ) : null}

              {(detail.status === "running" || detail.status === "pending") ? <JobProgressBar job={detail} /> : null}

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
                <div className="metric-pill">
                  <span className="metric-label">Stage</span>
                  <strong>{detail.progress_stage ? titleCase(detail.progress_stage) : titleCase(detail.status)}</strong>
                </div>
                <div className="metric-pill">
                  <span className="metric-label">Requested backend</span>
                  <strong>{formatBackendLabel(detail.requested_execution_backend)}</strong>
                </div>
                <div className="metric-pill">
                  <span className="metric-label">Actual backend</span>
                  <strong>{formatBackendLabel(detail.actual_execution_backend ?? detail.requested_execution_backend)}</strong>
                </div>
              </section>

              {detail.backend_selection_reason ? (
                <div className={`info-strip${detail.backend_fallback_used ? " info-strip-warning" : ""}`} role="note">
                  <strong>{detail.backend_fallback_used ? "Backend fallback" : "Backend selection"}</strong>
                  <span>{detail.backend_selection_reason}</span>
                </div>
              ) : null}

              <KeyValueList
                items={[
                  { label: "Source file", value: detail.source_filename ?? "Not recorded" },
                  { label: "Source path", value: detail.source_path ?? "Not recorded" },
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
                  { label: "Preferred worker", value: detail.preferred_worker_id ?? "Automatic" },
                  { label: "Pinned worker", value: detail.pinned_worker_id ?? "No pin" },
                  { label: "Preferred backend override", value: detail.preferred_backend_override ? formatBackendLabel(detail.preferred_backend_override) : "None" },
                  { label: "Schedule", value: detail.schedule_summary ?? "Any time" },
                  { label: "Scheduled for", value: formatDateTime(detail.scheduled_for_at) },
                  { label: "Interrupted at", value: formatDateTime(detail.interrupted_at) },
                  { label: "Output path", value: detail.final_output_path ?? detail.output_path ?? "Not written yet" },
                ]}
              />

              {(detail.input_size_bytes != null || detail.video_space_saved_bytes != null) ? (
                <CollapsibleSection
                  title="Storage and compression"
                  subtitle="Total file savings and video-only compression reduction."
                >
                  <KeyValueList
                    items={[
                      { label: "Original size", value: formatBytes(detail.input_size_bytes) },
                      { label: "Output size", value: formatBytes(detail.output_size_bytes) },
                      { label: "Total saved", value: formatBytes(detail.space_saved_bytes) },
                      { label: "Video saved", value: formatBytes(detail.video_space_saved_bytes) },
                      { label: "Audio and subtitle saved", value: formatBytes(detail.non_video_space_saved_bytes) },
                      { label: "Video reduction", value: formatPercent(detail.compression_reduction_percent) },
                    ]}
                  />
                </CollapsibleSection>
              ) : null}

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
        return label.includes(search) || item.id.toLowerCase().includes(search) || item.source_path.toLowerCase().includes(search);
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

function JobProgressBar({
  job,
  compact = false,
}: {
  job: Pick<JobSummary, "progress_stage" | "progress_percent" | "progress_fps" | "progress_speed" | "progress_out_time_seconds" | "worker_name" | "status">;
  compact?: boolean;
}) {
  const percent = clampProgress(job.progress_percent);
  const stage = job.progress_stage ? titleCase(job.progress_stage) : titleCase(job.status);
  return (
    <div className={`job-progress-card${compact ? " job-progress-card-compact" : ""}`}>
      <div className="job-progress-header">
        <strong>{stage}</strong>
        <span>{percent == null ? "Starting…" : `${Math.round(percent)}%`}</span>
      </div>
      <div className="job-progress-track" aria-label="Job progress">
        <span className="job-progress-fill" style={{ width: `${percent ?? 6}%` }} />
      </div>
      <div className="job-progress-meta">
        <span>{job.worker_name ?? "Waiting for worker"}</span>
        {job.progress_out_time_seconds != null ? <span>{formatDurationSeconds(job.progress_out_time_seconds)}</span> : null}
        {job.progress_fps != null ? <span>{job.progress_fps.toFixed(1)} fps</span> : null}
        {job.progress_speed != null ? <span>{job.progress_speed.toFixed(2)}x</span> : null}
      </div>
    </div>
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

function jobPrimaryLabel(
  job: Pick<JobSummary, "source_filename" | "tracked_file_id">,
  files: FileSummary[],
) {
  if (job.source_filename) {
    return job.source_filename;
  }
  const trackedFile = files.find((item) => item.id === job.tracked_file_id);
  return trackedFile ? trackedFile.source_filename : `Tracked file ${shortId(job.tracked_file_id)}`;
}

function jobSecondaryLabel(job: Pick<JobSummary, "source_path" | "tracked_file_id" | "id">) {
  if (job.source_path) {
    return `${job.source_path} • Job ${shortId(job.id)}`;
  }
  return `Tracked file ${shortId(job.tracked_file_id)} • Job ${shortId(job.id)}`;
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
    running: jobs.filter((job) => job.status === "running").length,
    active: jobs.filter((job) => ["pending", "scheduled", "running"].includes(job.status)).length,
    attention: jobs.filter(
      (job) =>
        ["failed", "interrupted", "manual_review", "skipped"].includes(job.status) ||
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
  if (job.status === "scheduled") {
    return "Scheduled";
  }
  if (job.status === "interrupted") {
    return "Interrupted";
  }
  if (job.status === "running") {
    return "Running";
  }
  return "In queue";
}

function sortJobsForDisplay(jobs: JobSummary[]) {
  const rank: Record<string, number> = {
    running: 0,
    pending: 1,
    scheduled: 2,
    failed: 3,
    interrupted: 4,
    manual_review: 5,
    skipped: 6,
    completed: 7,
  };
  return [...jobs].sort((left, right) => {
    const statusDelta = (rank[left.status] ?? 99) - (rank[right.status] ?? 99);
    if (statusDelta !== 0) {
      return statusDelta;
    }
    return right.updated_at.localeCompare(left.updated_at);
  });
}

function clampProgress(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return null;
  }
  return Math.max(0, Math.min(100, value));
}

function formatPercent(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "Not measured";
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)}%`;
}

function formatBackendLabel(value: string | null | undefined) {
  if (!value) {
    return "Not recorded";
  }
  return {
    cpu: "CPU",
    cpu_only: "CPU",
    intel_igpu: "Intel iGPU",
    prefer_intel_igpu: "Intel iGPU",
    nvidia_gpu: "NVIDIA",
    prefer_nvidia_gpu: "NVIDIA",
    amd_gpu: "AMD",
    prefer_amd_gpu: "AMD",
  }[value] ?? value.replace(/_/g, " ");
}
