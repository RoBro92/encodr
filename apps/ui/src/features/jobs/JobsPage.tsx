import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useSession } from "../auth/AuthProvider";
import {
  useCancelJobMutation,
  useCreateJobMutation,
  useFilesQuery,
  useJobDetailQuery,
  useJobsQuery,
  useRetryJobMutation,
  useRunWorkerOnceMutation,
  useWorkerStatusQuery,
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

type JobWorkerGroup = {
  key: string;
  label: string;
  kindSummary: string;
  jobs: JobSummary[];
  initiallyOpen: boolean;
  totalDurationSeconds: number | null;
  totalInputSizeBytes: number | null;
  totalOutputSizeBytes: number | null;
  totalSavedBytes: number | null;
  totalAudioTracksRemoved: number;
  totalSubtitleTracksRemoved: number;
};

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
  const cancelMutation = useCancelJobMutation();
  const createJobMutation = useCreateJobMutation();
  const runOnceMutation = useRunWorkerOnceMutation();
  const workerStatusQuery = useWorkerStatusQuery();
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const error = filterFilesQuery.error ?? createFilesQuery.error ?? jobsQuery.error ?? detailQuery.error;
  const filterFiles = filterFilesQuery.data?.items ?? [];
  const createFiles = createFilesQuery.data?.items ?? [];
  const files = deduplicateTrackedFiles([...filterFiles, ...createFiles]);
  const jobs = jobsQuery.data?.items ?? [];
  const orderedJobs = sortJobsForDisplay(jobs);
  const groupedJobs = groupJobsByWorker(orderedJobs);
  const localWorkerId = workerStatusQuery.data?.worker_id ?? null;
  const detail = detailQuery.data;
  const metrics = summariseJobs(jobs);
  const canRetry = detail ? ["failed", "interrupted", "manual_review", "skipped"].includes(detail.status) : false;
  const selectedJobId = detail?.id;

  useEffect(() => {
    setExpandedGroups((current) => {
      const next: Record<string, boolean> = {};
      let changed = false;
      for (const group of groupedJobs) {
        if (current[group.key] == null) {
          next[group.key] = group.initiallyOpen;
          changed = true;
        } else {
          next[group.key] = current[group.key];
        }
      }
      for (const key of Object.keys(current)) {
        if (!(key in next)) {
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [groupedJobs]);

  if (jobsQuery.isLoading || filterFilesQuery.isLoading || createFilesQuery.isLoading) {
    return <LoadingBlock label="Loading jobs" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load jobs" message={error.message} />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Jobs"
        title="Jobs"
        description="Monitor running work, inspect outcomes, and retry jobs that need another pass."
        actions={(
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
        )}
      />

      {retryMutation.error instanceof Error ? (
        <ErrorPanel title="Retry failed" message={retryMutation.error.message} />
      ) : null}
      {cancelMutation.error instanceof Error ? (
        <ErrorPanel title="Cancel failed" message={cancelMutation.error.message} />
      ) : null}
      {createJobMutation.error instanceof Error ? (
        <ErrorPanel title="Job creation failed" message={createJobMutation.error.message} />
      ) : null}
      {runOnceMutation.error instanceof Error ? (
        <ErrorPanel title="Worker run failed" message={runOnceMutation.error.message} />
      ) : null}

      <section className="jobs-metrics-grid" aria-label="Jobs metrics">
        <div className="jobs-metric">
          <span className="metric-label">Visible jobs</span>
          <strong>{metrics.total}</strong>
        </div>
        <div className="jobs-metric">
          <span className="metric-label">Running now</span>
          <strong>{metrics.running}</strong>
        </div>
        <div className="jobs-metric">
          <span className="metric-label">Needs attention</span>
          <strong>{metrics.attention}</strong>
        </div>
        <div className="jobs-metric">
          <span className="metric-label">Completed</span>
          <strong>{metrics.completed}</strong>
        </div>
      </section>

      <SectionCard title="Queue controls" subtitle="Filter the queue or create a job from a tracked file.">
        <div className="jobs-controls-stack">
          <div className="jobs-filter-grid">
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
          </div>
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
            <div className="job-worker-groups" role="list" aria-label="Jobs list">
              {groupedJobs.map((group) => (
                <section key={group.key} className="job-worker-group">
                  <button
                    className="job-worker-group-summary job-worker-group-trigger"
                    type="button"
                    aria-expanded={expandedGroups[group.key] ?? group.initiallyOpen}
                    onClick={() =>
                      setExpandedGroups((current) => ({
                        ...current,
                        [group.key]: !(current[group.key] ?? group.initiallyOpen),
                      }))
                    }
                  >
                    <div className="job-worker-group-heading">
                      <strong>{group.label}</strong>
                      <span>{group.kindSummary}</span>
                    </div>
                    <div className="job-worker-group-metrics">
                      {workerGroupStatsLabels(group).map((label) => (
                        <span key={label}>{label}</span>
                      ))}
                    </div>
                  </button>
                  {expandedGroups[group.key] ?? group.initiallyOpen ? (
                    <div className="record-list">
                      {group.jobs.map((item) => {
                        const isActive = item.id === jobId;
                        return (
                          <article
                            key={item.id}
                            className={`record-list-item queue-job-card${isActive ? " record-list-item-active" : ""}`}
                          >
                            <div className="queue-job-card-body">
                              <JobArtwork jobId={item.id} title={jobPrimaryLabel(item, files)} />
                              <div className="queue-job-card-content">
                                <div className="queue-job-card-header">
                                  <div className="queue-job-card-title-block">
                                    <div className="queue-job-card-title-row">
                                      <Link className="queue-job-card-title text-link" to={APP_ROUTES.jobDetail(item.id)}>
                                        <strong>{jobPrimaryLabel(item, files)}</strong>
                                      </Link>
                                      <div className="badge-row queue-job-card-badges">
                                        <StatusBadge value={displayJobStatus(item)} />
                                        {item.job_kind === "dry_run" ? <StatusBadge value="dry run" /> : null}
                                        {item.requires_review ? <StatusBadge value={item.review_status ?? "open"} /> : null}
                                        {item.tracked_file_is_protected ? <StatusBadge value="protected" /> : null}
                                        {(item.actual_execution_backend ?? item.requested_execution_backend) ? (
                                          <StatusBadge value={formatBackendLabel(item.actual_execution_backend ?? item.requested_execution_backend)} />
                                        ) : null}
                                        {item.backend_fallback_used ? <StatusBadge value="cpu fallback" /> : null}
                                      </div>
                                    </div>
                                    <div className="queue-job-card-context" title={jobSecondaryLabel(item)}>
                                      <span className="queue-job-card-path">{jobContextPathLabel(item)}</span>
                                      <span className="queue-job-card-id">Job {shortId(item.id)}</span>
                                    </div>
                                  </div>
                                  <div className="queue-job-card-state">
                                    <span className={`queue-job-card-status queue-job-card-status-${jobStatusTone(item)}`}>
                                      {formatStatusLabel(displayJobStatus(item))}
                                    </span>
                                    <span>{formatDateTime(item.updated_at)}</span>
                                  </div>
                                </div>
                                <p className="queue-job-card-metadata">{jobMediaInfoLabel(item)}</p>
                                <JobProgressBar job={item} compact />
                                {item.job_kind === "dry_run" && item.analysis_payload?.summary ? (
                                  <p className="queue-job-card-message">{item.analysis_payload.summary}</p>
                                ) : null}
                                {item.status === "completed" ? (
                                  <p className="queue-job-card-message">{replacementSummary(item)}</p>
                                ) : null}
                              </div>
                            </div>
                            <div className="section-card-actions queue-job-card-actions">
                              <Link className="button button-secondary button-small" to={APP_ROUTES.jobDetail(item.id)}>
                                Open
                              </Link>
                              {canCancelJob(item, localWorkerId) ? (
                                <button
                                  className="button button-secondary button-small"
                                  type="button"
                                  onClick={() => cancelMutation.mutate(item.id)}
                                  disabled={cancelMutation.isPending}
                                >
                                  {cancelMutation.isPending ? "Cancelling…" : "Cancel"}
                                </button>
                              ) : null}
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  ) : null}
                </section>
              ))}
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
            actions={(
              <div className="section-card-actions">
                {canRetry ? (
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
                ) : null}
                {canCancelJob(detail, localWorkerId) ? (
                  <button
                    className="button button-secondary button-small"
                    type="button"
                    onClick={() => cancelMutation.mutate(detail.id)}
                    disabled={cancelMutation.isPending}
                  >
                    {cancelMutation.isPending ? "Cancelling…" : "Cancel job"}
                  </button>
                ) : null}
              </div>
            )}
          >
            <div className="card-stack">
              <div className="badge-row">
                <StatusBadge value={displayJobStatus(detail)} />
                <StatusBadge value={detail.verification_status} />
                <StatusBadge value={detail.replacement_status} />
                {detail.requires_review ? <StatusBadge value={detail.review_status ?? "open"} /> : null}
                {detail.tracked_file_is_protected ? <StatusBadge value="protected" /> : null}
                {detail.job_kind === "dry_run" ? <StatusBadge value="dry run" /> : null}
              </div>

              {isOperatorCancelled(detail) ? (
                <div className="info-strip">
                  <strong>Cancelled</strong>
                  <span>{detail.failure_message ?? "This job was cancelled by the operator."}</span>
                </div>
              ) : null}

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
                  <strong>{isOperatorCancelled(detail) ? "Cancelled" : "Interrupted"}</strong>
                  <span>{detail.interruption_reason}</span>
                </div>
              ) : null}

              {detail.failure_message && !isOperatorCancelled(detail) ? (
                <div className="info-strip info-strip-danger">
                  <strong>Failure</strong>
                  <span>{detail.failure_message}</span>
                </div>
              ) : null}

              {detail.job_kind === "dry_run" ? (
                <div className="info-strip">
                  <strong>Dry run analysis</strong>
                  <span>This job inspected the file on a worker and stored a safe plan without transcoding or replacing media.</span>
                </div>
              ) : null}

              <JobProgressBar job={detail} />

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
                  <strong>{describeJobProgress(detail).stageLabel}</strong>
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

              {detail.job_kind === "dry_run" && detail.analysis_payload ? (
                <CollapsibleSection
                  title="Dry run output"
                  subtitle="Planned action, estimated size, and what would change."
                >
                  <KeyValueList
                    items={[
                      { label: "Planned action", value: titleCase(detail.analysis_payload.planned_action) },
                      { label: "Output filename", value: detail.analysis_payload.output_filename },
                      { label: "Current size", value: formatBytes(detail.analysis_payload.current_size_bytes) },
                      { label: "Estimated output size", value: formatBytes(detail.analysis_payload.estimated_output_size_bytes) },
                      { label: "Estimated saved", value: formatBytes(detail.analysis_payload.estimated_space_saved_bytes) },
                      { label: "Video handling", value: titleCase(detail.analysis_payload.video_handling) },
                      { label: "Audio tracks removed", value: detail.analysis_payload.audio_tracks_removed_count },
                      { label: "Subtitle tracks removed", value: detail.analysis_payload.subtitle_tracks_removed_count },
                      { label: "Would trigger manual review", value: detail.analysis_payload.requires_review ? "Yes" : "No" },
                      {
                        label: "Manual review reasons",
                        value: detail.analysis_payload.manual_review_reasons.length > 0
                          ? detail.analysis_payload.manual_review_reasons.join(" • ")
                          : "None",
                      },
                      { label: "Summary", value: detail.analysis_payload.summary },
                    ]}
                  />
                </CollapsibleSection>
              ) : null}

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

function JobArtwork({ jobId, title }: { jobId: string; title: string }) {
  const { tokens } = useSession();
  const [artworkUrl, setArtworkUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!tokens?.access_token) {
      setArtworkUrl(null);
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    fetch(`/api/jobs/${jobId}/artwork`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          return null;
        }
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        setArtworkUrl(objectUrl);
        return null;
      })
      .catch(() => {
        setArtworkUrl(null);
      });
    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [jobId, tokens?.access_token]);

  if (!artworkUrl) {
    return null;
  }

  return <img className="job-artwork" src={artworkUrl} alt={`${title} artwork`} />;
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
        const labelText = formatTrackedFileOption(item).toLowerCase();
        return labelText.includes(search) || item.id.toLowerCase().includes(search) || item.source_path.toLowerCase().includes(search);
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
  job: Pick<
    JobSummary,
    | "progress_stage"
    | "progress_percent"
    | "progress_fps"
    | "progress_speed"
    | "progress_out_time_seconds"
    | "progress_updated_at"
    | "worker_name"
    | "status"
    | "failure_category"
    | "failure_message"
    | "job_kind"
  >;
  compact?: boolean;
}) {
  const progress = describeJobProgress(job);
  const tone = jobProgressTone(job, progress.stalled);
  const metaLabel = compact && progress.metaLabel === job.worker_name
    ? null
    : progress.metaLabel ?? job.worker_name ?? "Waiting for worker";
  const statItems = [
    job.progress_out_time_seconds != null ? formatDurationSeconds(job.progress_out_time_seconds) : null,
    job.progress_fps != null ? `${job.progress_fps.toFixed(1)} fps` : null,
    job.progress_speed != null ? `${job.progress_speed.toFixed(2)}x` : null,
  ].filter((item): item is string => item != null);
  return (
    <div className={`job-progress-card job-progress-card-${tone}${compact ? " job-progress-card-compact" : ""}`}>
      <div className="job-progress-header">
        <strong>{progress.stageLabel}</strong>
        <span>{progress.percentLabel}</span>
      </div>
      <div className="job-progress-track" aria-label="Job progress">
        <span className="job-progress-fill" style={{ width: `${progress.barPercent}%` }} />
      </div>
      {statItems.length > 0 ? (
        <div className="job-progress-stats">
          {statItems.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : null}
      {metaLabel || progress.detail ? (
        <div className="job-progress-meta">
          {metaLabel ? <span>{metaLabel}</span> : null}
          {progress.detail ? <span>{progress.detail}</span> : null}
        </div>
      ) : null}
      {compact && job.failure_message ? (
        <p className="job-progress-error">{job.failure_message}</p>
      ) : null}
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

function jobContextPathLabel(job: Pick<JobSummary, "source_path" | "tracked_file_id">) {
  return job.source_path ?? `Tracked file ${shortId(job.tracked_file_id)}`;
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
    const statusDelta = (rank[normalisedJobStatus(left)] ?? 99) - (rank[normalisedJobStatus(right)] ?? 99);
    if (statusDelta !== 0) {
      return statusDelta;
    }
    return right.updated_at.localeCompare(left.updated_at);
  });
}

function canCancelJob(
  job: Pick<JobSummary, "id" | "status" | "assigned_worker_id" | "job_kind">,
  localWorkerId: string | null,
) {
  if (job.status === "pending" || job.status === "scheduled") {
    return true;
  }
  if (job.status !== "running") {
    return false;
  }
  if (job.job_kind === "dry_run") {
    return false;
  }
  return Boolean(localWorkerId && job.assigned_worker_id === localWorkerId);
}

type JobStatusWithFailureCategory = {
  status: string;
  failure_category?: string | null;
};

function normalisedJobStatus(job: JobStatusWithFailureCategory) {
  return isOperatorCancelled(job) ? "cancelled" : job.status;
}

function displayJobStatus(job: JobStatusWithFailureCategory) {
  return normalisedJobStatus(job);
}

function formatStatusLabel(value: string) {
  return value.replace(/_/g, " ").toUpperCase();
}

function jobStatusTone(job: JobStatusWithFailureCategory) {
  const status = normalisedJobStatus(job);
  if (["failed", "interrupted", "cancelled", "manual_review"].includes(status)) {
    return "danger";
  }
  if (["pending", "scheduled", "skipped"].includes(status)) {
    return "warning";
  }
  if (status === "completed") {
    return "success";
  }
  if (status === "running") {
    return "active";
  }
  return "neutral";
}

function isOperatorCancelled(job: JobStatusWithFailureCategory) {
  return job.status === "interrupted" && job.failure_category === "cancelled_by_operator";
}

function jobProgressTone(job: JobStatusWithFailureCategory, stalled: boolean) {
  const status = normalisedJobStatus(job);
  if (["failed", "interrupted", "cancelled", "manual_review"].includes(status)) {
    return "danger";
  }
  if (["pending", "scheduled"].includes(status)) {
    return "waiting";
  }
  if (stalled || status === "running") {
    return "running";
  }
  if (["completed", "skipped"].includes(status)) {
    return "complete";
  }
  return "neutral";
}

function describeJobProgress(
  job: Pick<
    JobSummary,
    | "progress_stage"
    | "progress_percent"
    | "progress_updated_at"
    | "status"
    | "failure_category"
    | "worker_name"
    | "job_kind"
  >,
) {
  const status = normalisedJobStatus(job);
  const staleAgeSeconds = staleProgressAgeSeconds(job.progress_updated_at);
  const stalled = status === "running" && staleAgeSeconds != null && staleAgeSeconds >= 180;
  const percent = clampProgress(job.progress_percent);
  const rawStage = job.progress_stage ?? status;

  let stageLabel = titleCase(rawStage.replace(/_/g, " "));
  if (status === "pending") {
    stageLabel = job.job_kind === "dry_run" ? "Queued For Analysis" : "Queued";
  } else if (status === "scheduled") {
    stageLabel = "Scheduled";
  } else if (status === "cancelled") {
    stageLabel = "Cancelled";
  } else if (status === "interrupted") {
    stageLabel = "Interrupted";
  } else if (rawStage === "starting") {
    stageLabel = "Preparing";
  } else if (rawStage === "probing" || rawStage === "planning" || rawStage === "summarising") {
    stageLabel = "Analysing";
  } else if (rawStage === "encoding" && (percent ?? 0) === 0) {
    stageLabel = "Initialising Backend";
  }
  if (stalled) {
    stageLabel = "Stalled";
  }

  const percentLabel =
    status === "scheduled"
      ? "Waiting"
      : status === "pending"
        ? "Queued"
        : status === "completed"
          ? "Done"
          : status === "skipped"
            ? "Skipped"
            : status === "manual_review"
              ? "Needs review"
              : status === "failed"
                ? "Failed"
                : status === "interrupted"
                  ? "Stopped"
        : status === "cancelled"
          ? "Stopped"
          : percent == null
            ? rawStage === "starting" || rawStage === "probing" || rawStage === "planning" || rawStage === "summarising"
              ? "Starting…"
              : "Awaiting progress"
            : `${Math.round(percent)}%`;

  const detail =
    stalled && staleAgeSeconds != null
      ? `No progress update for ${formatDurationSeconds(staleAgeSeconds)}`
      : rawStage === "encoding" && (percent ?? 0) === 0
        ? "Worker is preparing the backend before meaningful output begins."
        : rawStage === "probing" || rawStage === "planning" || rawStage === "summarising"
          ? "Inspecting the media and building a safe plan."
          : null;

  return {
    stageLabel,
    percentLabel,
    barPercent: percent ?? (status === "running" ? 6 : status === "completed" ? 100 : 4),
    metaLabel:
      status === "scheduled"
        ? "Waiting for schedule window"
        : status === "pending"
          ? "Waiting for worker"
          : job.worker_name ?? "Waiting for worker",
    detail,
    stalled,
  };
}

function staleProgressAgeSeconds(progressUpdatedAt: string | null) {
  if (!progressUpdatedAt) {
    return null;
  }
  const updatedAt = Date.parse(progressUpdatedAt);
  if (Number.isNaN(updatedAt)) {
    return null;
  }
  return Math.max(0, Math.round((Date.now() - updatedAt) / 1000));
}

function groupJobsByWorker(jobs: JobSummary[]): JobWorkerGroup[] {
  const grouped = new Map<string, JobSummary[]>();
  for (const job of jobs) {
    const key = job.assigned_worker_id ?? job.worker_name ?? "automatic";
    const existing = grouped.get(key);
    if (existing) {
      existing.push(job);
    } else {
      grouped.set(key, [job]);
    }
  }

  return [...grouped.entries()].map(([key, items]) => {
    const kinds = new Set(items.map((item) => item.job_kind));
    return {
      key,
      label: workerGroupLabel(items[0]),
      kindSummary:
        kinds.size === 1 && kinds.has("dry_run")
          ? "Dry run queue"
          : kinds.has("dry_run")
            ? "Execution and dry-run jobs"
            : "Execution queue",
      jobs: items,
      initiallyOpen: items.some((item) => item.status === "running" || item.status === "pending"),
      totalDurationSeconds: sumNullable(items.map((item) => item.duration_seconds)),
      totalInputSizeBytes: sumNullable(items.map((item) => item.input_size_bytes)),
      totalOutputSizeBytes: sumNullable(items.map((item) => item.output_size_bytes)),
      totalSavedBytes: sumNullable(items.map((item) => item.space_saved_bytes)),
      totalAudioTracksRemoved: items.reduce((sum, item) => sum + (item.audio_tracks_removed_count ?? 0), 0),
      totalSubtitleTracksRemoved: items.reduce((sum, item) => sum + (item.subtitle_tracks_removed_count ?? 0), 0),
    };
  });
}

function sumNullable(values: Array<number | null>) {
  const present = values.filter((value): value is number => typeof value === "number");
  if (present.length === 0) {
    return null;
  }
  return present.reduce((sum, value) => sum + value, 0);
}

function formatDurationTotal(value: number | null) {
  if (value == null) {
    return "No recorded duration";
  }
  return formatDurationSeconds(value);
}

function workerGroupStatsLabels(group: JobWorkerGroup) {
  return [
    `${group.jobs.length} file${group.jobs.length === 1 ? "" : "s"}`,
    formatDurationTotal(group.totalDurationSeconds),
    `Start ${formatBytes(group.totalInputSizeBytes)}`,
    `Output ${formatBytes(group.totalOutputSizeBytes)}`,
    `Saved ${formatBytes(group.totalSavedBytes)}`,
    `${group.totalAudioTracksRemoved} audio removed`,
    `${group.totalSubtitleTracksRemoved} subtitles removed`,
  ];
}

function workerGroupLabel(job: JobSummary) {
  if (job.worker_name) {
    return job.worker_name;
  }
  if (job.assigned_worker_id) {
    return `Worker ${shortId(job.assigned_worker_id)}`;
  }
  if (job.preferred_worker_id) {
    return `Preferred worker ${shortId(job.preferred_worker_id)}`;
  }
  return "Automatic assignment";
}

function jobMediaInfoLabel(job: JobSummary) {
  const parts = [];
  if (job.job_kind === "dry_run") {
    if (job.output_size_bytes != null) {
      parts.push(`Estimated Output ${formatBytes(job.output_size_bytes)}`);
    }
    if (job.input_size_bytes != null) {
      parts.push(`Start ${formatBytes(job.input_size_bytes)}`);
    }
    if (job.space_saved_bytes != null) {
      parts.push(`Saved ${formatBytes(job.space_saved_bytes)}`);
    }
  } else {
    if (job.input_size_bytes != null) {
      parts.push(`Start ${formatBytes(job.input_size_bytes)}`);
    }
    if (job.output_size_bytes != null) {
      parts.push(`Output ${formatBytes(job.output_size_bytes)}`);
    }
    if (job.space_saved_bytes != null) {
      parts.push(`Saved ${formatBytes(job.space_saved_bytes)}`);
    }
  }
  if (job.audio_tracks_removed_count > 0) {
    parts.push(`${job.audio_tracks_removed_count} audio removed`);
  }
  if (job.subtitle_tracks_removed_count > 0) {
    parts.push(`${job.subtitle_tracks_removed_count} subtitles removed`);
  }
  if (job.duration_seconds != null) {
    parts.push(formatDurationSeconds(job.duration_seconds));
  }
  return parts.join(" • ") || "Media summary pending";
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
