import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { useSession } from "../auth/AuthProvider";
import {
  useCancelJobMutation,
  useClearQueueMutation,
  useCreateJobMutation,
  useDeleteJobBackupMutation,
  useFilesQuery,
  useJobBackupsQuery,
  useJobDetailQuery,
  useJobProgressStream,
  useJobsQuery,
  useRetryJobMutation,
  useResolveFailedJobsMutation,
  useRestoreJobBackupMutation,
  useStripOnlyRecoveryMutation,
  useWorkerStatusQuery,
} from "../../lib/api/hooks";
import type {
  AudioStreamDecision,
  FileSummary,
  JobBackup,
  JobDetail,
  JobSummary,
  RetryJobPayload,
  SubtitleStreamDecision,
} from "../../lib/types/api";
import { formatBitrate, formatBytes, formatDateTime, formatDurationSeconds, titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

const JOB_STATUS_OPTIONS = [
  { label: "Any status", value: "" },
  { label: "Pending", value: "pending" },
  { label: "Scheduled", value: "scheduled" },
  { label: "Running", value: "running" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
  { label: "Interrupted", value: "interrupted" },
  { label: "Cancelled", value: "cancelled" },
  { label: "Manual review", value: "manual_review" },
  { label: "Skipped", value: "skipped" },
];

type JobsTab = "active" | "completed" | "problem";
type ConfirmAction = "clear-queue" | null;
type ResolveProblemAction = "retry" | "skip";
type BackupRetryStrategy = NonNullable<RetryJobPayload["existing_backup_strategy"]>;
const BACKUP_PAGE_SIZE = 15;
const COMPLETED_JOB_PAGE_SIZE = 10;
const PROBLEM_JOB_PAGE_SIZE = 10;
const ARTWORK_CONCURRENCY_LIMIT = 4;
const NO_ARTWORK_CACHE = new Set<string>();
const ARTWORK_URL_CACHE = new Map<string, string>();
const ARTWORK_QUEUE: Array<() => void> = [];
let activeArtworkRequests = 0;

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
  useJobProgressStream();
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const status = normaliseStatusFilter(searchParams.get("status"));
  const [fileId, setFileId] = useState("");
  const [fileSearch, setFileSearch] = useState("");
  const [createFromFileId, setCreateFromFileId] = useState("");
  const [createFileSearch, setCreateFileSearch] = useState("");
  const [jobsTab, setJobsTab] = useState<JobsTab>(jobsTabFromQuery(searchParams.get("tab"), searchParams.get("status")));
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);
  const [backupSearch, setBackupSearch] = useState("");
  const [backupPage, setBackupPage] = useState(0);
  const [selectedBackupIds, setSelectedBackupIds] = useState<Set<string>>(new Set());
  const [completedSearch, setCompletedSearch] = useState("");
  const [completedStatus, setCompletedStatus] = useState("");
  const [completedPage, setCompletedPage] = useState(0);
  const [problemSearch, setProblemSearch] = useState("");
  const [problemPage, setProblemPage] = useState(0);
  const [selectedProblemJobIds, setSelectedProblemJobIds] = useState<Set<string>>(new Set());
  const [selectedResolveJobIds, setSelectedResolveJobIds] = useState<string[] | null>(null);
  const [mixedProblemSelectionOpen, setMixedProblemSelectionOpen] = useState(false);
  const [backupRetryJobIds, setBackupRetryJobIds] = useState<string[] | null>(null);
  const [stripOnlyRecoveryJobId, setStripOnlyRecoveryJobId] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      status: status || undefined,
      file_id: fileId || undefined,
      limit: 100,
    }),
    [fileId, status],
  );
  const problemFilters = useMemo(
    () => ({
      status_group: "problem",
      status: status && tabForStatus(status) === "problem" ? status : undefined,
      search: problemSearch.trim() || undefined,
      file_id: fileId || undefined,
      limit: PROBLEM_JOB_PAGE_SIZE,
      offset: problemPage * PROBLEM_JOB_PAGE_SIZE,
    }),
    [fileId, problemPage, problemSearch, status],
  );
  const effectiveCompletedStatus = status && tabForStatus(status) === "completed" ? status : completedStatus;
  const completedFilters = useMemo(
    () => ({
      status_group: "completed",
      status: effectiveCompletedStatus || undefined,
      search: completedSearch.trim() || undefined,
      file_id: fileId || undefined,
      limit: COMPLETED_JOB_PAGE_SIZE,
      offset: completedPage * COMPLETED_JOB_PAGE_SIZE,
    }),
    [completedPage, completedSearch, effectiveCompletedStatus, fileId],
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
  const completedJobsQuery = useJobsQuery(completedFilters);
  const problemJobsQuery = useJobsQuery(problemFilters);
  const detailQuery = useJobDetailQuery(jobId);
  const retryMutation = useRetryJobMutation();
  const stripOnlyRecoveryMutation = useStripOnlyRecoveryMutation();
  const cancelMutation = useCancelJobMutation();
  const clearQueueMutation = useClearQueueMutation();
  const resolveFailedMutation = useResolveFailedJobsMutation();
  const createJobMutation = useCreateJobMutation();
  const backupFilters = useMemo(
    () => ({
      search: backupSearch.trim() || undefined,
      limit: BACKUP_PAGE_SIZE,
      offset: backupPage * BACKUP_PAGE_SIZE,
    }),
    [backupPage, backupSearch],
  );
  const jobBackupsQuery = useJobBackupsQuery(backupFilters);
  const deleteBackupMutation = useDeleteJobBackupMutation();
  const restoreBackupMutation = useRestoreJobBackupMutation();
  const workerStatusQuery = useWorkerStatusQuery();
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const error = filterFilesQuery.error ?? createFilesQuery.error ?? jobsQuery.error ?? detailQuery.error;
  const filterFiles = filterFilesQuery.data?.items ?? [];
  const createFiles = createFilesQuery.data?.items ?? [];
  const files = deduplicateTrackedFiles([...filterFiles, ...createFiles]);
  const jobs = jobsQuery.data?.items ?? [];
  const orderedJobs = sortJobsForDisplay(jobs);
  const problemPageJobs = problemJobsQuery.data?.items ?? [];
  const completedPageJobs = completedJobsQuery.data?.items ?? [];
  const completedTotal = completedJobsQuery.data?.total ?? completedPageJobs.length;
  const completedTotalPages = Math.max(1, Math.ceil(completedTotal / COMPLETED_JOB_PAGE_SIZE));
  const completedPageStart = completedTotal === 0 ? 0 : Math.min(completedPage * COMPLETED_JOB_PAGE_SIZE + 1, completedTotal);
  const completedPageEnd = Math.min((completedPage + 1) * COMPLETED_JOB_PAGE_SIZE, completedTotal);
  const problemTotal = problemJobsQuery.data?.total ?? problemPageJobs.length;
  const problemTotalPages = Math.max(1, Math.ceil(problemTotal / PROBLEM_JOB_PAGE_SIZE));
  const problemPageStart = problemTotal === 0 ? 0 : Math.min(problemPage * PROBLEM_JOB_PAGE_SIZE + 1, problemTotal);
  const problemPageEnd = Math.min((problemPage + 1) * PROBLEM_JOB_PAGE_SIZE, problemTotal);
  const activeJobs = orderedJobs.filter(isActiveQueueJob);
  const clearableQueueJobs = orderedJobs.filter((job) =>
    ["pending", "scheduled"].includes(normalisedJobStatus(job))
    || isRetryableInterruptedForQueueClear(job),
  );
  const tabJobs = jobsTab === "problem" ? problemPageJobs : jobsTab === "completed" ? completedPageJobs : jobsForTab(orderedJobs, jobsTab);
  const tabJobsTotal = jobsTab === "problem" ? problemTotal : jobsTab === "completed" ? completedTotal : tabJobs.length;
  const groupedJobs = groupJobsByWorker(tabJobs);
  const localWorkerId = workerStatusQuery.data?.worker_id ?? null;
  const detail = detailQuery.data;
  const metrics = summariseJobs(jobs);
  const canStripOnlyRecovery = detail ? canRecoverWithStripOnly(detail) : false;
  const canRetry = detail ? ["failed", "interrupted", "cancelled", "manual_review", "skipped"].includes(detail.status) && !canStripOnlyRecovery : false;
  const selectedJobId = detail?.id;
  const backupItems = jobBackupsQuery.data?.items ?? [];
  const backupTotal = jobBackupsQuery.data?.total ?? backupItems.length;
  const backupTotalPages = Math.max(1, Math.ceil(backupTotal / BACKUP_PAGE_SIZE));
  const backupPageStart = backupTotal === 0 ? 0 : Math.min(backupPage * BACKUP_PAGE_SIZE + 1, backupTotal);
  const backupPageEnd = Math.min((backupPage + 1) * BACKUP_PAGE_SIZE, backupTotal);
  const selectedVisibleBackupCount = backupItems.filter((item) => selectedBackupIds.has(item.job_id)).length;
  const allVisibleBackupsSelected = backupItems.length > 0 && selectedVisibleBackupCount === backupItems.length;
  const selectedProblemJobs = problemPageJobs.filter((job) => selectedProblemJobIds.has(job.id));
  const selectedVisibleProblemCount = selectedProblemJobs.length;
  const allVisibleProblemsSelected = problemPageJobs.length > 0 && selectedVisibleProblemCount === problemPageJobs.length;
  const selectedProblemJobIdsArray = [...selectedProblemJobIds];
  const selectedProblemBackupCollision = selectedProblemJobs.length > 0
    && selectedProblemJobs.every((job) => isBackupAlreadyExistsJob(job) && hasAvailableBackupForRetry(job));
  const jobsQuerySyncKey = searchParams.toString();

  function closeDrawer() {
    navigate(jobsRouteWithStatus(status));
  }

  function updateStatusFilter(nextStatus: string) {
    setJobsTab(nextStatus ? tabForStatus(nextStatus) : "active");
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (nextStatus) {
        next.set("status", nextStatus);
        next.set("tab", tabForStatus(nextStatus));
      } else {
        next.delete("status");
        next.delete("tab");
      }
      return next;
    });
  }

  function updateJobsTab(nextTab: JobsTab) {
    setJobsTab(nextTab);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      const currentStatus = normaliseStatusFilter(next.get("status"));
      if (currentStatus && tabForStatus(currentStatus) !== nextTab) {
        next.delete("status");
      }
      next.set("tab", nextTab);
      return next;
    });
  }

  function updateCompletedStatusFilter(nextStatus: string) {
    setCompletedStatus(nextStatus);
    setCompletedPage(0);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("tab", "completed");
      next.delete("status");
      return next;
    });
  }

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

  useEffect(() => {
    if (detail) {
      setJobsTab(tabForJob(detail));
    }
  }, [detail?.id, detail?.status, detail?.failure_category]);

  useEffect(() => {
    if (!jobId && (searchParams.has("tab") || searchParams.has("status"))) {
      const queryTab = jobsTabFromQuery(searchParams.get("tab"), status);
      setJobsTab(queryTab);
    }
  }, [jobId, jobsQuerySyncKey, searchParams, status]);

  useEffect(() => {
    setBackupPage(0);
    setSelectedBackupIds(new Set());
  }, [backupSearch]);

  useEffect(() => {
    setProblemPage(0);
    setSelectedProblemJobIds(new Set());
  }, [fileId, problemSearch, status]);

  useEffect(() => {
    setCompletedPage(0);
  }, [completedSearch, effectiveCompletedStatus, fileId]);

  useEffect(() => {
    setSelectedProblemJobIds((current) => {
      const visible = new Set(problemPageJobs.map((job) => job.id));
      const next = new Set([...current].filter((jobId) => visible.has(jobId)));
      return next.size === current.size ? current : next;
    });
  }, [problemPageJobs]);

  useEffect(() => {
    if (!problemJobsQuery.data) {
      return;
    }
    const lastPage = Math.max(0, Math.ceil(problemTotal / PROBLEM_JOB_PAGE_SIZE) - 1);
    if (problemPage > lastPage) {
      setProblemPage(lastPage);
    }
  }, [problemJobsQuery.data, problemPage, problemTotal]);

  useEffect(() => {
    if (!completedJobsQuery.data) {
      return;
    }
    const lastPage = Math.max(0, Math.ceil(completedTotal / COMPLETED_JOB_PAGE_SIZE) - 1);
    if (completedPage > lastPage) {
      setCompletedPage(lastPage);
    }
  }, [completedJobsQuery.data, completedPage, completedTotal]);

  useEffect(() => {
    setSelectedBackupIds((current) => {
      const visible = new Set(backupItems.map((item) => item.job_id));
      const next = new Set([...current].filter((jobId) => visible.has(jobId)));
      return next.size === current.size ? current : next;
    });
  }, [backupItems]);

  useEffect(() => {
    if (!jobBackupsQuery.data) {
      return;
    }
    const lastPage = Math.max(0, Math.ceil(backupTotal / BACKUP_PAGE_SIZE) - 1);
    if (backupPage > lastPage) {
      setBackupPage(lastPage);
    }
  }, [backupPage, backupTotal, jobBackupsQuery.data]);

  const isProblemInitialLoading = jobsTab === "problem" && problemJobsQuery.isLoading && !problemJobsQuery.data;
  const isCompletedInitialLoading = jobsTab === "completed" && completedJobsQuery.isLoading && !completedJobsQuery.data;
  const loadError = error
    ?? (jobsTab === "problem" ? problemJobsQuery.error : null)
    ?? (jobsTab === "completed" ? completedJobsQuery.error : null);

  if (jobsQuery.isLoading || isProblemInitialLoading || isCompletedInitialLoading || filterFilesQuery.isLoading || createFilesQuery.isLoading) {
    return <LoadingBlock label="Loading jobs" />;
  }

  if (loadError instanceof Error) {
    return <ErrorPanel title="Unable to load jobs" message={loadError.message} />;
  }

  function validateProblemSelection() {
    if (selectedProblemJobIdsArray.length <= 1) {
      return true;
    }
    if (problemSelectionErrorKeys(selectedProblemJobs).length <= 1) {
      return true;
    }
    setMixedProblemSelectionOpen(true);
    return false;
  }

  function openSelectedResolveModal() {
    if (selectedProblemJobIdsArray.length === 0 || !validateProblemSelection()) {
      return;
    }
    setSelectedResolveJobIds(selectedProblemJobIdsArray);
  }

  function resolveProblemJobs(action: ResolveProblemAction) {
    const jobIds = selectedResolveJobIds ?? [];
    if (jobIds.length === 0) {
      return;
    }
    resolveFailedMutation.mutate(
      { job_ids: jobIds, action },
      {
        onSuccess: () => {
          setSelectedResolveJobIds(null);
          setSelectedProblemJobIds(new Set());
        },
      },
    );
  }

  function openBackupRetryModal(jobIds: string[]) {
    if (jobIds.length === 0 || !validateProblemSelection()) {
      return;
    }
    setBackupRetryJobIds(jobIds);
  }

  function retryBackupJobs(strategy: BackupRetryStrategy) {
    const jobIds = backupRetryJobIds ?? [];
    if (jobIds.length === 0) {
      return;
    }
    resolveFailedMutation.mutate(
      { job_ids: jobIds, action: "retry", existing_backup_strategy: strategy },
      {
        onSuccess: () => {
          setBackupRetryJobIds(null);
          setSelectedProblemJobIds(new Set());
        },
      },
    );
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Jobs"
        title="Jobs"
        description="Monitor running jobs, inspect outcomes, and retry jobs that need another pass."
      />

      {retryMutation.error instanceof Error ? (
        <ErrorPanel title="Retry failed" message={retryMutation.error.message} />
      ) : null}
      {stripOnlyRecoveryMutation.error instanceof Error ? (
        <ErrorPanel title="Strip-only recovery failed" message={stripOnlyRecoveryMutation.error.message} />
      ) : null}
      {cancelMutation.error instanceof Error ? (
        <ErrorPanel title="Cancel failed" message={cancelMutation.error.message} />
      ) : null}
      {createJobMutation.error instanceof Error ? (
        <ErrorPanel title="Job creation failed" message={createJobMutation.error.message} />
      ) : null}
      {clearQueueMutation.error instanceof Error ? (
        <ErrorPanel title="Clear queue failed" message={clearQueueMutation.error.message} />
      ) : null}
      {resolveFailedMutation.error instanceof Error ? (
        <ErrorPanel title="Resolve failed jobs failed" message={resolveFailedMutation.error.message} />
      ) : null}
      {deleteBackupMutation.error instanceof Error ? (
        <ErrorPanel title="Backup delete failed" message={deleteBackupMutation.error.message} />
      ) : null}
      {restoreBackupMutation.error instanceof Error ? (
        <ErrorPanel title="Backup restore failed" message={restoreBackupMutation.error.message} />
      ) : null}

      <section className="metrics-card-grid" aria-label="Jobs metrics">
        <div className="metrics-card-item">
          <span className="metrics-card-label">Visible jobs</span>
          <strong className="metrics-card-value">{metrics.total}</strong>
        </div>
        <div className="metrics-card-item">
          <span className="metrics-card-label">Running now</span>
          <strong className="metrics-card-value">{metrics.running}</strong>
        </div>
        <div className="metrics-card-item">
          <span className="metrics-card-label">Needs attention</span>
          <strong className="metrics-card-value">{metrics.attention}</strong>
        </div>
        <div className="metrics-card-item">
          <span className="metrics-card-label">Completed</span>
          <strong className="metrics-card-value">{metrics.completed}</strong>
        </div>
      </section>

      <SectionCard
        title="Queue controls"
        subtitle="Filter and create jobs, or clear stalled queued work."
        actions={
          <>
            <button
              className="button button-secondary button-small"
              type="button"
              onClick={() => setConfirmAction("clear-queue")}
              disabled={clearQueueMutation.isPending || clearableQueueJobs.length === 0}
            >
              {clearQueueMutation.isPending ? "Clearing…" : "Clear queue"}
            </button>
          </>
        }
      >
        <div className="jobs-control-bar">
          <div className="jobs-control-group jobs-control-group-filters">
            <label className="field">
              <span>Status</span>
              <select aria-label="Status" value={status} onChange={(event) => updateStatusFilter(event.target.value)}>
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
            className="jobs-control-group jobs-create-inline"
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

      <section className="jobs-review-layout jobs-review-layout-single">
        <SectionCard title={jobsTabTitle(jobsTab)} subtitle={`${tabJobsTotal} job${tabJobsTotal === 1 ? "" : "s"} in view`}>
          <div className="jobs-tab-bar" role="tablist" aria-label="Job queue sections">
            <button
              className={`jobs-tab${jobsTab === "active" ? " jobs-tab-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={jobsTab === "active"}
              onClick={() => updateJobsTab("active")}
            >
              Active Queue <span>{activeJobs.length}</span>
            </button>
            <button
              className={`jobs-tab${jobsTab === "completed" ? " jobs-tab-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={jobsTab === "completed"}
              onClick={() => updateJobsTab("completed")}
            >
              Completed <span>{completedTotal}</span>
            </button>
            <button
              className={`jobs-tab${jobsTab === "problem" ? " jobs-tab-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={jobsTab === "problem"}
              onClick={() => updateJobsTab("problem")}
            >
              Failed / Cancelled <span>{problemTotal}</span>
            </button>
          </div>

          {jobsTab === "completed" ? (
            <>
              <div className="backup-toolbar problem-toolbar">
                <label className="field backup-search-field">
                  <span>Search completed jobs</span>
                  <input
                    aria-label="Search completed jobs"
                    value={completedSearch}
                    placeholder="Search by file or worker"
                    onChange={(event) => setCompletedSearch(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Completed job status</span>
                  <select
                    aria-label="Completed job status"
                    value={effectiveCompletedStatus}
                    onChange={(event) => updateCompletedStatusFilter(event.target.value)}
                  >
                    <option value="">Completed and skipped</option>
                    <option value="completed">Completed</option>
                    <option value="skipped">Skipped</option>
                  </select>
                </label>
              </div>
              <div className="backup-pagination problem-pagination" aria-label="Completed job pagination">
                <span>
                  Showing {completedPageStart}-{completedPageEnd} of {completedTotal}
                </span>
                <div className="section-card-actions">
                  <button
                    className="button button-secondary button-small"
                    type="button"
                    onClick={() => setCompletedPage((current) => Math.max(0, current - 1))}
                    disabled={completedPage === 0}
                  >
                    Previous
                  </button>
                  <button
                    className="button button-secondary button-small"
                    type="button"
                    onClick={() => setCompletedPage((current) => Math.min(completedTotalPages - 1, current + 1))}
                    disabled={completedPage >= completedTotalPages - 1}
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          ) : null}

          {jobsTab === "problem" ? (
            <>
              <div className="backup-toolbar problem-toolbar">
                <label className="field backup-search-field">
                  <span>Search failed and cancelled jobs</span>
                  <input
                    aria-label="Search failed and cancelled jobs"
                    value={problemSearch}
                    placeholder="Search by file, worker, or error"
                    onChange={(event) => setProblemSearch(event.target.value)}
                  />
                </label>
                <div className="backup-toolbar-actions">
                  <button
                    className="button button-secondary button-small"
                    type="button"
                    onClick={() => {
                      setSelectedProblemJobIds((current) => {
                        const next = new Set(current);
                        if (allVisibleProblemsSelected) {
                          problemPageJobs.forEach((item) => next.delete(item.id));
                        } else {
                          problemPageJobs.forEach((item) => next.add(item.id));
                        }
                        return next;
                      });
                    }}
                    disabled={problemPageJobs.length === 0}
                  >
                    {allVisibleProblemsSelected ? "Clear visible problem selection" : "Select all visible problem jobs"}
                  </button>
                  <button
                    className="button button-secondary button-small"
                    type="button"
                    onClick={openSelectedResolveModal}
                    disabled={selectedProblemJobIds.size === 0 || resolveFailedMutation.isPending}
                  >
                    {resolveFailedMutation.isPending
                      ? "Resolving…"
                      : `Resolve selected${selectedProblemJobIds.size > 0 ? ` (${selectedProblemJobIds.size})` : ""}`}
                  </button>
                  {selectedProblemBackupCollision ? (
                    <button
                      className="button button-primary button-small"
                      type="button"
                      onClick={() => openBackupRetryModal(selectedProblemJobIdsArray)}
                      disabled={resolveFailedMutation.isPending}
                    >
                      Backup options ({selectedProblemJobIds.size})
                    </button>
                  ) : null}
                </div>
              </div>
              <div className="backup-pagination problem-pagination" aria-label="Failed and cancelled job pagination">
                <span>
                  Showing {problemPageStart}-{problemPageEnd} of {problemTotal}
                </span>
                <div className="section-card-actions">
                  <button
                    className="button button-secondary button-small"
                    type="button"
                    onClick={() => setProblemPage((current) => Math.max(0, current - 1))}
                    disabled={problemPage === 0}
                  >
                    Previous
                  </button>
                  <button
                    className="button button-secondary button-small"
                    type="button"
                    onClick={() => setProblemPage((current) => Math.min(problemTotalPages - 1, current + 1))}
                    disabled={problemPage >= problemTotalPages - 1}
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          ) : null}

          {tabJobs.length === 0 ? (
            <EmptyState title={emptyTitleForTab(jobsTab)} message={emptyMessageForTab(jobsTab)} />
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
                              {jobsTab === "problem" ? (
                                <label className="problem-job-checkbox">
                                  <input
                                    type="checkbox"
                                    aria-label={`Select problem job ${jobPrimaryLabel(item, files)}`}
                                    checked={selectedProblemJobIds.has(item.id)}
                                    onChange={(event) => {
                                      setSelectedProblemJobIds((current) => {
                                        const next = new Set(current);
                                        if (event.target.checked) {
                                          next.add(item.id);
                                        } else {
                                          next.delete(item.id);
                                        }
                                        return next;
                                      });
                                    }}
                                  />
                                </label>
                              ) : null}
                              <JobArtwork jobId={item.id} title={jobPrimaryLabel(item, files)} />
                              <div className="queue-job-card-content">
                                <div className="queue-job-card-header">
                                  <div className="queue-job-card-title-block">
                                    <div className="queue-job-card-title-row">
                                      <Link className="queue-job-card-title text-link" to={jobDetailRouteWithStatus(item.id, status)}>
                                        <strong>{jobPrimaryLabel(item, files)}</strong>
                                      </Link>
                                      <JobStatusBadgeRow job={item} />
                                    </div>
                                    <div className="queue-job-card-context">
                                      <span className="queue-job-card-path" title={jobContextPathLabel(item)}>{jobContextPathLabel(item)}</span>
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
                                <JobMetadataBadges items={jobMediaInfoItems(item)} />
                                <JobProgressBar job={item} compact />
                                {item.job_kind === "dry_run" && item.analysis_payload?.summary ? (
                                  <p className="queue-job-card-message">{item.analysis_payload.summary}</p>
                                ) : null}
                                {item.status === "completed" ? (
                                  <p className="queue-job-card-message">{replacementSummary(item)}</p>
                                ) : null}
                                {normalisedJobStatus(item) === "skipped" ? (
                                  <p className="queue-job-card-message">Skipped: {skippedReason(item)}</p>
                                ) : null}
                              </div>
                            </div>
                            <div className="section-card-actions queue-job-card-actions">
                              <Link className="button button-secondary button-small" to={jobDetailRouteWithStatus(item.id, status)}>
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
                              {jobsTab === "problem" && isBackupAlreadyExistsJob(item) && hasAvailableBackupForRetry(item) ? (
                                <button
                                  className="button button-primary button-small"
                                  type="button"
                                  onClick={() => {
                                    setBackupRetryJobIds([item.id]);
                                  }}
                                  disabled={retryMutation.isPending}
                                >
                                  Backup options
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
      </section>

      <SectionCard title="Backups" subtitle="Original files retained by completed replacement jobs.">
        <div className="backup-toolbar">
          <label className="field backup-search-field">
            <span>Search backups</span>
            <input
              aria-label="Search backups"
              value={backupSearch}
              placeholder="Search by file or path"
              onChange={(event) => setBackupSearch(event.target.value)}
            />
          </label>
          <div className="backup-toolbar-actions">
            <button
              className="button button-secondary button-small"
              type="button"
              onClick={() => {
                setSelectedBackupIds((current) => {
                  const next = new Set(current);
                  if (allVisibleBackupsSelected) {
                    backupItems.forEach((item) => next.delete(item.job_id));
                  } else {
                    backupItems.forEach((item) => next.add(item.job_id));
                  }
                  return next;
                });
              }}
              disabled={backupItems.length === 0}
            >
              {allVisibleBackupsSelected ? "Clear visible selection" : "Select all visible"}
            </button>
            <button
              className="button button-secondary button-small"
              type="button"
              onClick={() => {
                const selected = [...selectedBackupIds];
                if (selected.length === 0) {
                  return;
                }
                if (!window.confirm(`Delete ${selected.length} selected backup file${selected.length === 1 ? "" : "s"}? This cannot be undone.`)) {
                  return;
                }
                void Promise.all(selected.map((backupJobId) => deleteBackupMutation.mutateAsync(backupJobId)))
                  .then(() => {
                    setSelectedBackupIds(new Set());
                  })
                  .catch(() => undefined);
              }}
              disabled={selectedBackupIds.size === 0 || deleteBackupMutation.isPending}
            >
              {deleteBackupMutation.isPending ? "Deleting…" : `Delete selected${selectedBackupIds.size > 0 ? ` (${selectedBackupIds.size})` : ""}`}
            </button>
          </div>
        </div>
        {jobBackupsQuery.isLoading ? (
          <LoadingBlock label="Loading backups" />
        ) : backupItems.length || backupTotal > 0 ? (
          <>
            {backupItems.length ? (
              <div className="backup-list" role="list" aria-label="Job backups">
                {backupItems.map((item) => (
                  <BackupRow
                    key={item.job_id}
                    item={item}
                    selected={selectedBackupIds.has(item.job_id)}
                    onSelectedChange={(selected) => {
                      setSelectedBackupIds((current) => {
                        const next = new Set(current);
                        if (selected) {
                          next.add(item.job_id);
                        } else {
                          next.delete(item.job_id);
                        }
                        return next;
                      });
                    }}
                    onDelete={() => {
                      if (window.confirm("Delete this backup file? This cannot be undone.")) {
                        deleteBackupMutation.mutate(item.job_id);
                      }
                    }}
                    onRestore={() => {
                      if (window.confirm("Restore this backup and move the current replacement aside?")) {
                        restoreBackupMutation.mutate(item.job_id);
                      }
                    }}
                    isBusy={deleteBackupMutation.isPending || restoreBackupMutation.isPending}
                  />
                ))}
              </div>
            ) : (
              <EmptyState title="No backups on this page" message="This page no longer has backup records." />
            )}
            <div className="backup-pagination" aria-label="Backup pagination">
              <span>
                Showing {backupPageStart}-{backupPageEnd} of {backupTotal}
              </span>
              <div className="section-card-actions">
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => setBackupPage((current) => Math.max(0, current - 1))}
                  disabled={backupPage === 0}
                >
                  Previous
                </button>
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => setBackupPage((current) => Math.min(backupTotalPages - 1, current + 1))}
                  disabled={backupPage >= backupTotalPages - 1}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        ) : (
          <EmptyState title="No backups tracked" message="Backups from completed replacement jobs will appear here." />
        )}
      </SectionCard>

      {confirmAction ? (
        <ConfirmBulkActionModal
          activeCount={clearableQueueJobs.length}
          isPending={clearQueueMutation.isPending}
          onClose={() => {
            setConfirmAction(null);
          }}
          onConfirm={() => {
            if (confirmAction === "clear-queue") {
              clearQueueMutation.mutate(undefined, {
                onSuccess: () => {
                  setConfirmAction(null);
                },
              });
            }
          }}
        />
      ) : null}

      {selectedResolveJobIds ? (
        <ResolveProblemJobsModal
          count={selectedResolveJobIds.length}
          isPending={resolveFailedMutation.isPending}
          onClose={() => setSelectedResolveJobIds(null)}
          onResolve={resolveProblemJobs}
        />
      ) : null}

      {mixedProblemSelectionOpen ? (
        <MixedProblemSelectionModal onClose={() => setMixedProblemSelectionOpen(false)} />
      ) : null}

      {backupRetryJobIds ? (
        <BackupRetryModal
          count={backupRetryJobIds.length}
          isPending={resolveFailedMutation.isPending}
          onCancel={() => setBackupRetryJobIds(null)}
          onRetry={retryBackupJobs}
        />
      ) : null}

      {stripOnlyRecoveryJobId ? (
        <StripOnlyRecoveryModal
          isPending={stripOnlyRecoveryMutation.isPending}
          onCancel={() => setStripOnlyRecoveryJobId(null)}
          onConfirm={() => {
            stripOnlyRecoveryMutation.mutate(stripOnlyRecoveryJobId, {
              onSuccess: () => {
                setStripOnlyRecoveryJobId(null);
              },
            });
          }}
        />
      ) : null}

      {jobId ? (
        <JobDetailDrawer
          detail={detail}
          files={files}
          isLoading={detailQuery.isLoading}
          canRetry={canRetry}
          canStripOnlyRecovery={canStripOnlyRecovery}
          canCancel={detail ? canCancelJob(detail, localWorkerId) : false}
          isRetryPending={retryMutation.isPending}
          isStripOnlyRecoveryPending={stripOnlyRecoveryMutation.isPending}
          isCancelPending={cancelMutation.isPending}
          onClose={closeDrawer}
          onRetry={() => {
            if (selectedJobId) {
              if (detail && isBackupAlreadyExistsJob(detail) && hasAvailableBackupForRetry(detail)) {
                setBackupRetryJobIds([selectedJobId]);
              } else {
                retryMutation.mutate(selectedJobId);
              }
            }
          }}
          onStripOnlyRecovery={() => {
            if (selectedJobId) {
              setStripOnlyRecoveryJobId(selectedJobId);
            }
          }}
          onCancel={() => {
            if (detail) {
              cancelMutation.mutate(detail.id);
            }
          }}
        />
      ) : null}
    </div>
  );
}

function JobStatusBadgeRow({
  job,
  includeVerification = false,
}: {
  job: JobSummary | JobDetail;
  includeVerification?: boolean;
}) {
  const badges = [
    jobBadge(job),
    workerBadge(job),
    reviewBadge(job),
    backendBadge(job),
    scheduleBadge(job),
  ];

  if (job.job_kind === "dry_run") {
    badges.push({
      label: "Type",
      value: "Dry run",
      tone: "info",
      title: "This job only analysed planned work and did not replace media.",
    });
  }
  if (includeVerification) {
    badges.push({
      label: "Verify",
      value: titleCase(job.verification_status),
      tone: statusToneForValue(job.verification_status),
      title: "Probe and verification result recorded before replacement.",
    });
    badges.push({
      label: "Replace",
      value: titleCase(job.replacement_status),
      tone: statusToneForValue(job.replacement_status),
      title: "Final replacement state for the source file.",
    });
  }

  return (
    <div className="badge-row queue-job-card-badges">
      {badges.map((badge) => (
        <ExplainedStatusBadge
          key={`${badge.label}:${badge.value}`}
          label={badge.label}
          value={badge.value}
          tone={badge.tone}
          title={badge.title}
        />
      ))}
    </div>
  );
}

function ExplainedStatusBadge({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: string;
  tone: "neutral" | "info" | "success" | "warning" | "danger" | "active";
  title: string;
}) {
  return (
    <span className={`explained-status-badge explained-status-badge-${tone}`} title={title}>
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function ConfirmBulkActionModal({
  activeCount,
  isPending,
  onClose,
  onConfirm,
}: {
  activeCount: number;
  isPending: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Clear queue"
    >
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Clear active queue?</strong>
              <p className="muted-copy">
                {`${activeCount} queued, scheduled, retryable interrupted, or waiting job${activeCount === 1 ? "" : "s"} will be cancelled. Running jobs are left alone.`}
            </p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary" type="button" onClick={onClose} disabled={isPending}>
              Keep
            </button>
            <button className="button button-primary" type="button" onClick={onConfirm} disabled={isPending}>
              {isPending ? "Clearing…" : "Clear queue"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function MixedProblemSelectionModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Mixed problem selection">
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Mixed problem selection</strong>
            <p className="muted-copy">Select jobs with the same error before using a bulk action.</p>
          </div>
          <div className="section-card-actions">
            <button className="button button-primary" type="button" onClick={onClose}>
              OK
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function ResolveProblemJobsModal({
  count,
  isPending,
  onClose,
  onResolve,
}: {
  count: number;
  isPending: boolean;
  onClose: () => void;
  onResolve: (action: ResolveProblemAction) => void;
}) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Resolve selected failed jobs">
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Resolve selected jobs?</strong>
            <p className="muted-copy">
              Retry moves {count} selected job{count === 1 ? "" : "s"} back to the queue. Mark skipped completes them as skipped so they will not be processed.
            </p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary" type="button" onClick={onClose} disabled={isPending}>
              Cancel
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => onResolve("skip")}
              disabled={isPending}
            >
              Mark skipped
            </button>
            <button
              className="button button-primary"
              type="button"
              onClick={() => onResolve("retry")}
              disabled={isPending}
            >
              {isPending ? "Resolving…" : "Retry selected"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function BackupRetryModal({
  count,
  isPending,
  onCancel,
  onRetry,
}: {
  count: number;
  isPending: boolean;
  onCancel: () => void;
  onRetry: (strategy: BackupRetryStrategy) => void;
}) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Backup already exists">
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Backup already exists</strong>
            <p className="muted-copy">
              Choose how to handle the existing backup before retrying {count} selected job{count === 1 ? "" : "s"}.
            </p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary" type="button" onClick={onCancel} disabled={isPending}>
              Cancel
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => onRetry("keep_existing_backup")}
              disabled={isPending}
            >
              Keep original
            </button>
            <button
              className="button button-primary"
              type="button"
              onClick={() => onRetry("replace_backup")}
              disabled={isPending}
            >
              Replace backup
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function StripOnlyRecoveryModal({
  isPending,
  onCancel,
  onConfirm,
}: {
  isPending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Skip transcode / strip only">
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Skip transcode / strip only</strong>
            <p className="muted-copy">
              This keeps the original video stream unchanged and only cleans audio and subtitle tracks using the current profile policy.
              The file is marked complete only after strip-only verification and replacement succeed.
            </p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary" type="button" onClick={onCancel} disabled={isPending}>
              Cancel
            </button>
            <button className="button button-primary" type="button" onClick={onConfirm} disabled={isPending}>
              {isPending ? "Queueing…" : "Skip transcode / strip only"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function BackupRow({
  item,
  selected,
  onSelectedChange,
  onDelete,
  onRestore,
  isBusy,
}: {
  item: JobBackup;
  selected: boolean;
  onSelectedChange: (selected: boolean) => void;
  onDelete: () => void;
  onRestore: () => void;
  isBusy: boolean;
}) {
  return (
    <article className="backup-list-row" role="listitem">
      <label className="backup-row-checkbox">
        <input
          type="checkbox"
          aria-label={`Select backup for ${item.source_filename ?? item.backup_path}`}
          checked={selected}
          onChange={(event) => onSelectedChange(event.target.checked)}
        />
      </label>
      <div>
        <strong>{item.source_filename ?? item.source_path?.split("/").pop() ?? `Job ${shortId(item.job_id)}`}</strong>
        <p className="muted-copy">{item.source_path ?? "Source path unavailable"}</p>
        <p className="muted-copy">
          Backup {item.backup_path} • {formatBackupPolicy(item.backup_policy)}
          {item.retention_until ? ` • retain until ${formatDateTime(item.retention_until)}` : ""}
        </p>
      </div>
      <div className="section-card-actions">
        <button className="button button-secondary button-small" type="button" onClick={onRestore} disabled={isBusy}>
          Restore
        </button>
        <button className="button button-secondary button-small" type="button" onClick={onDelete} disabled={isBusy}>
          Delete
        </button>
      </div>
    </article>
  );
}

function JobDetailDrawer({
  detail,
  files,
  isLoading,
  canRetry,
  canStripOnlyRecovery,
  canCancel,
  isRetryPending,
  isStripOnlyRecoveryPending,
  isCancelPending,
  onClose,
  onRetry,
  onStripOnlyRecovery,
  onCancel,
}: {
  detail: JobDetail | undefined;
  files: FileSummary[];
  isLoading: boolean;
  canRetry: boolean;
  canStripOnlyRecovery: boolean;
  canCancel: boolean;
  isRetryPending: boolean;
  isStripOnlyRecoveryPending: boolean;
  isCancelPending: boolean;
  onClose: () => void;
  onRetry: () => void;
  onStripOnlyRecovery: () => void;
  onCancel: () => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const title = detail ? jobPrimaryLabel(detail, files) : "Selected job";

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, [detail?.id]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <>
      <button
        className="job-drawer-backdrop"
        type="button"
        aria-label="Close selected job"
        onClick={onClose}
      />
      <aside className="job-drawer-panel" role="dialog" aria-modal="true" aria-labelledby="job-drawer-title">
        <header className="job-drawer-header">
          <div className="job-drawer-title">
            <h2 id="job-drawer-title">{title}</h2>
            {detail ? <JobStatusBadgeRow job={detail} includeVerification /> : null}
          </div>
          <button
            ref={closeButtonRef}
            className="job-drawer-close"
            type="button"
            aria-label="Close selected job"
            onClick={onClose}
          >
            X
          </button>
        </header>

        <div className="job-drawer-body">
          {isLoading ? (
            <LoadingBlock label="Loading job detail" />
          ) : detail ? (
            <div className="job-drawer-stack">
              <JobDrawerCallouts detail={detail} />

              <JobProgressBar job={detail} />

              <section className="job-drawer-metrics" aria-label="Job metrics">
                <JobDrawerMetric label="Worker" value={detail.worker_name ?? "Not assigned"} />
                <JobDrawerMetric label="Attempts" value={detail.attempt_count} />
                <JobDrawerMetric label="Updated" value={formatDateTime(detail.updated_at)} />
                <JobDrawerMetric label="Stage" value={describeJobProgress(detail).stageLabel} />
                <JobDrawerMetric label="Requested backend" value={formatBackendLabel(detail.requested_execution_backend)} />
                <JobDrawerMetric label="Actual backend" value={formatBackendLabel(detail.actual_execution_backend ?? detail.requested_execution_backend)} />
              </section>

              {detail.backend_selection_reason ? (
                <JobDrawerCallout
                  tone={detail.backend_fallback_used ? "warning" : "info"}
                  title={detail.backend_fallback_used ? "Backend fallback" : "Backend selection"}
                >
                  {detail.backend_selection_reason}
                </JobDrawerCallout>
              ) : null}

              <section className="job-drawer-metadata" aria-label="Job metadata">
                <JobMetadataItem label="Source file" value={detail.source_filename} />
                <JobMetadataItem
                  label="Review state"
                  value={
                    detail.requires_review ? (
                      <Link className="text-link" to={APP_ROUTES.reviewDetail(detail.tracked_file_id)}>
                        {detail.review_status ?? "open"}
                      </Link>
                    ) : (
                      "No review required"
                    )
                  }
                />
                <JobMetadataItem label="Started" value={detail.started_at ? formatDateTime(detail.started_at) : null} />
                <JobMetadataItem label="Completed" value={detail.completed_at ? formatDateTime(detail.completed_at) : null} />
                <JobMetadataItem label="Interrupted at" value={detail.interrupted_at ? formatDateTime(detail.interrupted_at) : null} />
                <JobMetadataItem label="Source path" value={detail.source_path} wide breakAll />
                <JobMetadataItem label="Output path" value={detail.final_output_path ?? detail.output_path} wide breakAll emptyLabel="Not written yet" />
              </section>

              <div className="job-drawer-accordions">
                <CollapsibleSection
                  title="Advanced scheduling details"
                  subtitle="Worker targeting, tracking UUIDs, and schedule windows"
                >
                  <section className="job-drawer-scheduling-grid" aria-label="Advanced scheduling details">
                    <JobMetadataItem label="Tracked file" value={detail.tracked_file_id} mono breakAll />
                    <JobMetadataItem
                      label="Protected file"
                      value={
                        detail.tracked_file_is_protected ? (
                          <Link className="text-link" to={APP_ROUTES.reviewDetail(detail.tracked_file_id)}>
                            View review item
                          </Link>
                        ) : (
                          "No"
                        )
                      }
                    />
                    <JobMetadataItem label="Preferred worker" value={detail.preferred_worker_id ?? <MutedValue>Automatic</MutedValue>} mono breakAll />
                    <JobMetadataItem label="Pinned worker" value={detail.pinned_worker_id} mono breakAll />
                    <JobMetadataItem label="Preferred backend override" value={detail.preferred_backend_override ? formatBackendLabel(detail.preferred_backend_override) : null} />
                    <JobMetadataItem label="Schedule" value={detail.schedule_summary ?? "Any time"} />
                    <JobMetadataItem label="Scheduled for" value={detail.scheduled_for_at ? formatDateTime(detail.scheduled_for_at) : null} />
                  </section>
                </CollapsibleSection>

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
                        { label: "Source video bitrate", value: formatBitrate(detail.analysis_payload.source_video_bitrate_bps) },
                        { label: "Estimated output bitrate", value: formatBitrate(detail.analysis_payload.estimated_output_video_bitrate_bps) },
                        { label: "Effective CRF", value: detail.analysis_payload.target_crf ?? <MutedValue>Profile default</MutedValue> },
                        { label: "Low-bitrate skip threshold", value: formatBitrate(detail.analysis_payload.low_bitrate_skip_threshold_bps) },
                        { label: "Minimum output bitrate", value: formatBitrate(detail.analysis_payload.minimum_output_bitrate_bps) },
                        {
                          label: "Reduction review threshold",
                          value: detail.analysis_payload.max_allowed_video_reduction_percent == null
                            ? <MutedValue>Not configured</MutedValue>
                            : `${detail.analysis_payload.max_allowed_video_reduction_percent}%`,
                        },
                        {
                          label: "Output growth review",
                          value: detail.analysis_payload.output_larger_than_input_review_percent == null
                            ? <MutedValue>Not configured</MutedValue>
                            : `${detail.analysis_payload.output_larger_than_input_review_percent}%`,
                        },
                        { label: "Audio tracks removed", value: detail.analysis_payload.audio_tracks_removed_count },
                        { label: "Subtitle tracks removed", value: detail.analysis_payload.subtitle_tracks_removed_count },
                        { label: "Would trigger manual review", value: detail.analysis_payload.requires_review ? "Yes" : "No" },
                        {
                          label: "Manual review reasons",
                          value: detail.analysis_payload.manual_review_reasons.length > 0
                            ? detail.analysis_payload.manual_review_reasons.join(" • ")
                            : <MutedValue>Not available</MutedValue>,
                        },
                        { label: "Summary", value: detail.analysis_payload.summary },
                        {
                          label: "Decision reasons",
                          value: detail.analysis_payload.reason_messages?.length
                            ? detail.analysis_payload.reason_messages.join(" • ")
                            : <MutedValue>Not available</MutedValue>,
                        },
                      ]}
                    />
                    <StreamDecisionList
                      title="Audio stream plan"
                      items={detail.analysis_payload.audio_stream_decisions}
                    />
                    <StreamDecisionList
                      title="Subtitle stream plan"
                      items={detail.analysis_payload.subtitle_stream_decisions}
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
                        { label: "Output growth", value: formatPercent(detail.output_growth_percent) },
                        {
                          label: "Output growth guard",
                          value: detail.output_growth_guard_percent == null
                            ? <MutedValue>Disabled</MutedValue>
                            : `${detail.output_growth_guard_percent}%`,
                        },
                      ]}
                    />
                  </CollapsibleSection>
                ) : null}

                <CollapsibleSection
                  title="Advanced execution details"
                  subtitle="Command, output streams, and worker stderr/stdout."
                >
                  <div className="job-drawer-execution-details">
                    <KeyValueList
                      items={[
                        { label: "Command", value: detail.execution_command ? <pre>{detail.execution_command.join(" ")}</pre> : <MutedValue>Not available</MutedValue> },
                        { label: "Stdout", value: detail.execution_stdout ? <pre>{detail.execution_stdout}</pre> : <MutedValue>Not available</MutedValue> },
                        { label: "Stderr", value: detail.execution_stderr ? <pre>{detail.execution_stderr}</pre> : <MutedValue>Not available</MutedValue> },
                      ]}
                    />
                  </div>
                </CollapsibleSection>

                <CollapsibleSection
                  title="Advanced verification details"
                  subtitle="Verification rules and recorded verification payload."
                >
                  <KeyValueList
                    items={[
                      { label: "Require verification", value: detail.require_verification ? "Yes" : "No" },
                      { label: "Keep original until verified", value: detail.keep_original_until_verified ? "Yes" : "No" },
                      { label: "Verification payload", value: detail.verification_payload ? <pre>{JSON.stringify(detail.verification_payload, null, 2)}</pre> : <MutedValue>Not available</MutedValue> },
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
                      { label: "Backup policy", value: formatBackupPolicy(detail.backup_policy) },
                      { label: "Delete replaced source", value: detail.delete_replaced_source ? "Yes" : "No" },
                      { label: "Backup path", value: detail.original_backup_path ?? <MutedValue>Not available</MutedValue> },
                      { label: "Backup retention", value: detail.backup_retention_until ? formatDateTime(detail.backup_retention_until) : <MutedValue>Not scheduled</MutedValue> },
                      { label: "Replacement failure", value: detail.replacement_failure_message ?? <MutedValue>None</MutedValue> },
                      { label: "Replacement payload", value: detail.replacement_payload ? <pre>{JSON.stringify(detail.replacement_payload, null, 2)}</pre> : <MutedValue>Not available</MutedValue> },
                    ]}
                  />
                </CollapsibleSection>
              </div>
            </div>
          ) : (
            <EmptyState title="No job selected" message="Choose a job to inspect its latest result." />
          )}
        </div>

        {detail && (canRetry || canStripOnlyRecovery || canCancel) ? (
          <footer className="job-drawer-footer">
            {canRetry ? (
              <button
                className="button button-primary"
                type="button"
                onClick={onRetry}
                disabled={isRetryPending}
              >
                {isRetryPending ? "Retrying…" : "Retry job"}
              </button>
            ) : null}
            {canStripOnlyRecovery ? (
              <button
                className="button button-primary"
                type="button"
                onClick={onStripOnlyRecovery}
                disabled={isStripOnlyRecoveryPending}
              >
                {isStripOnlyRecoveryPending ? "Queueing…" : "Skip transcode / strip only"}
              </button>
            ) : null}
            {canCancel ? (
              <button
                className="button button-secondary"
                type="button"
                onClick={onCancel}
                disabled={isCancelPending}
              >
                {isCancelPending ? "Cancelling…" : "Cancel job"}
              </button>
            ) : null}
          </footer>
        ) : null}
      </aside>
    </>
  );
}

function JobDrawerCallouts({ detail }: { detail: JobDetail }) {
  return (
    <section className="job-drawer-callout-stack" aria-label="Job status notices">
      {isOperatorCancelled(detail) ? (
        <JobDrawerCallout tone="danger" title="Cancelled">
          {detail.failure_message ?? "This job was cancelled by the operator."}
        </JobDrawerCallout>
      ) : null}

      {detail.status === "scheduled" && detail.schedule_summary ? (
        <JobDrawerCallout tone="warning" title="Scheduled">
          This job is waiting for its allowed execution window.
          {detail.scheduled_for_at ? ` Next opening: ${formatDateTime(detail.scheduled_for_at)}.` : ""}
        </JobDrawerCallout>
      ) : null}

      {normalisedJobStatus(detail) === "skipped" ? (
        <JobDrawerCallout tone="info" title="Skipped">
          {skippedReason(detail)}
        </JobDrawerCallout>
      ) : null}

      {detail.status === "interrupted" && detail.interruption_reason ? (
        <JobDrawerCallout tone="warning" title={isOperatorCancelled(detail) ? "Cancelled" : "Interrupted"}>
          {detail.interruption_reason}
        </JobDrawerCallout>
      ) : null}

      {detail.failure_message && !isOperatorCancelled(detail) ? (
        <JobDrawerCallout tone="danger" title="Failure">
          {detail.failure_message}
        </JobDrawerCallout>
      ) : null}

      {detail.job_kind === "dry_run" ? (
        <JobDrawerCallout tone="info" title="Dry run analysis">
          This job inspected the file on a worker and stored a safe plan without transcoding or replacing media.
        </JobDrawerCallout>
      ) : null}
    </section>
  );
}

function JobDrawerCallout({
  tone,
  title,
  children,
}: {
  tone: "info" | "warning" | "danger";
  title: string;
  children: ReactNode;
}) {
  return (
    <div className={`job-drawer-callout job-drawer-callout-${tone}`}>
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}

function JobDrawerMetric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="job-drawer-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function JobMetadataItem({
  label,
  value,
  wide = false,
  breakAll = false,
  mono = false,
  emptyLabel = "Not available",
}: {
  label: string;
  value: ReactNode | null | undefined;
  wide?: boolean;
  breakAll?: boolean;
  mono?: boolean;
  emptyLabel?: string;
}) {
  const isEmpty = value == null || value === "";
  return (
    <div className={`job-drawer-metadata-item${wide ? " job-drawer-metadata-item-wide" : ""}${breakAll ? " job-drawer-metadata-item-break" : ""}${mono ? " job-drawer-metadata-item-mono" : ""}`}>
      <span>{label}</span>
      <strong>{isEmpty ? <MutedValue>{emptyLabel}</MutedValue> : value}</strong>
    </div>
  );
}

function MutedValue({ children }: { children: ReactNode }) {
  return <span className="job-drawer-muted-value">{children}</span>;
}

function StreamDecisionList({
  title,
  items,
}: {
  title: string;
  items: AudioStreamDecision[] | SubtitleStreamDecision[];
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <>
      <h4>{title}</h4>
      <KeyValueList
        items={items.map((item) => ({
          label: streamDecisionLabel(item),
          value: streamDecisionValue(item),
        }))}
      />
    </>
  );
}

function streamDecisionLabel(item: AudioStreamDecision | SubtitleStreamDecision) {
  return `#${item.index} ${item.language.toUpperCase()}`;
}

function streamDecisionValue(item: AudioStreamDecision | SubtitleStreamDecision) {
  const action = item.selected ? "Keep" : "Remove";
  const markers = [
    item.codec,
    "channels" in item && item.channels != null ? `${item.channels} ch` : null,
    "channel_layout" in item ? item.channel_layout : null,
    item.default ? "default" : null,
    "forced" in item && item.forced ? "forced" : null,
    "hearing_impaired" in item && item.hearing_impaired ? "hearing impaired" : null,
    "commentary" in item && item.commentary ? "commentary" : null,
    item.title,
  ].filter((part): part is string => Boolean(part));
  return `${action} ${titleCase(item.role)} - ${titleCase(item.reason)}${markers.length > 0 ? ` - ${markers.join(" • ")}` : ""}`;
}

function JobArtwork({ jobId, title }: { jobId: string; title: string }) {
  const { tokens } = useSession();
  const placeholderRef = useRef<HTMLDivElement | null>(null);
  const [isVisible, setIsVisible] = useState(false);
  const [artworkUrl, setArtworkUrl] = useState<string | null>(null);

  useEffect(() => {
    const node = placeholderRef.current;
    if (!node) {
      return undefined;
    }
    if (!("IntersectionObserver" in window)) {
      setIsVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "160px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isVisible) {
      return undefined;
    }
    if (!tokens?.access_token) {
      setArtworkUrl(null);
      return;
    }
    const cachedUrl = ARTWORK_URL_CACHE.get(jobId);
    if (cachedUrl) {
      setArtworkUrl(cachedUrl);
      return undefined;
    }
    if (NO_ARTWORK_CACHE.has(jobId)) {
      setArtworkUrl(null);
      return undefined;
    }
    const controller = new AbortController();
    enqueueArtworkRequest(async () => {
      if (controller.signal.aborted) {
        return null;
      }
      const response = await fetch(`/api/jobs/${jobId}/artwork`, {
        headers: { Authorization: `Bearer ${tokens.access_token}` },
        signal: controller.signal,
      });
      if (!response.ok) {
        if (response.status === 404) {
          NO_ARTWORK_CACHE.add(jobId);
        }
        return null;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      ARTWORK_URL_CACHE.set(jobId, objectUrl);
      return objectUrl;
    })
      .then(async (response) => {
        if (response) {
          setArtworkUrl(response);
        }
        return null;
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          NO_ARTWORK_CACHE.add(jobId);
        }
        setArtworkUrl(null);
      });
    return () => {
      controller.abort();
    };
  }, [isVisible, jobId, tokens?.access_token]);

  if (!artworkUrl) {
    return <div ref={placeholderRef} className="job-artwork job-artwork-placeholder" aria-hidden="true" />;
  }

  return <img className="job-artwork" src={artworkUrl} alt={`${title} artwork`} />;
}

function enqueueArtworkRequest<T>(task: () => Promise<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const run = () => {
      activeArtworkRequests += 1;
      task()
        .then(resolve)
        .catch(reject)
        .finally(() => {
          activeArtworkRequests -= 1;
          const next = ARTWORK_QUEUE.shift();
          if (next) {
            next();
          }
        });
    };
    if (activeArtworkRequests < ARTWORK_CONCURRENCY_LIMIT) {
      run();
    } else {
      ARTWORK_QUEUE.push(run);
    }
  });
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

function JobMetadataBadges({ items }: { items: string[] }) {
  const labels = items.length > 0 ? items : ["Media summary pending"];
  return (
    <div className="queue-job-card-metadata-badges" aria-label="Job media metadata">
      {labels.map((item) => (
        <span key={item}>{item}</span>
      ))}
    </div>
  );
}

function jobsForTab(jobs: JobSummary[], tab: JobsTab) {
  if (tab === "active") {
    return jobs.filter(isActiveQueueJob);
  }
  if (tab === "completed") {
    return jobs.filter(isCompletedJob);
  }
  return jobs.filter(isProblemJob);
}

function jobsTabFromQuery(tab: string | null, status: string | null): JobsTab {
  if (tab === "completed" || status === "completed" || status === "skipped") {
    return "completed";
  }
  if (tab === "problem" || ["failed", "interrupted", "cancelled", "manual_review"].includes(status ?? "")) {
    return "problem";
  }
  return "active";
}

function tabForJob(job: JobSummary | JobDetail): JobsTab {
  if (isCompletedJob(job)) {
    return "completed";
  }
  if (isProblemJob(job)) {
    return "problem";
  }
  return "active";
}

function tabForStatus(status: string): JobsTab {
  if (["completed", "skipped"].includes(status)) {
    return "completed";
  }
  if (["failed", "interrupted", "cancelled", "manual_review"].includes(status)) {
    return "problem";
  }
  return "active";
}

function normaliseStatusFilter(value: string | null) {
  const allowed = new Set(JOB_STATUS_OPTIONS.map((option) => option.value));
  return value && allowed.has(value) ? value : "";
}

function jobsRouteWithStatus(status: string) {
  return status ? `${APP_ROUTES.jobs}?status=${encodeURIComponent(status)}` : APP_ROUTES.jobs;
}

function jobDetailRouteWithStatus(jobId: string, status: string) {
  return status
    ? `${APP_ROUTES.jobDetail(jobId)}?status=${encodeURIComponent(status)}`
    : APP_ROUTES.jobDetail(jobId);
}

function jobsTabTitle(tab: JobsTab) {
  if (tab === "active") {
    return "Active Queue";
  }
  if (tab === "completed") {
    return "Completed Jobs";
  }
  return "Failed / Cancelled / Interrupted";
}

function emptyTitleForTab(tab: JobsTab) {
  if (tab === "active") {
    return "No active queue";
  }
  if (tab === "completed") {
    return "No completed jobs";
  }
  return "No failed jobs";
}

function emptyMessageForTab(tab: JobsTab) {
  if (tab === "active") {
    return "Create jobs from Library to populate the queue.";
  }
  if (tab === "completed") {
    return "Successful jobs move here after verification and replacement finish.";
  }
  return "Failed, cancelled, interrupted, and review-held jobs will appear here.";
}

function isActiveQueueJob(job: JobSummary) {
  return ["pending", "scheduled", "running"].includes(normalisedJobStatus(job));
}

function isCompletedJob(job: JobSummary) {
  return ["completed", "skipped"].includes(normalisedJobStatus(job));
}

function isProblemJob(job: JobSummary) {
  return ["failed", "interrupted", "cancelled", "manual_review"].includes(normalisedJobStatus(job));
}

function canRecoverWithStripOnly(job: JobSummary | JobDetail) {
  if (!["failed", "cancelled", "manual_review"].includes(normalisedJobStatus(job))) {
    return false;
  }
  const code = (job.failure_code ?? "").toLowerCase();
  const category = (job.failure_category ?? "").toLowerCase();
  const message = [job.failure_message, job.skipped_reason]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  const guardCodes = new Set([
    "output_larger_than_input",
    "compression_safety_bitrate_floor",
    "compression_safety_exceeded",
    "compression_safety_unmeasurable",
  ]);
  if (guardCodes.has(code) || guardCodes.has(category)) {
    return true;
  }
  return /larger than (the )?source|output is larger|output grew|too small|bitrate (is )?below|compression safety/.test(message);
}

function problemSelectionErrorKeys(jobs: JobSummary[]) {
  return [...new Set(jobs.map(problemErrorKey))];
}

function problemErrorKey(
  job: Pick<JobSummary, "status" | "failure_code" | "failure_category" | "failure_message" | "skipped_reason">,
) {
  const code = job.failure_code ?? job.failure_category ?? "unknown";
  const message = normaliseProblemMessage(job.failure_message ?? job.skipped_reason ?? "");
  return `${code}:${message}`;
}

function normaliseProblemMessage(value: string) {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

function isBackupAlreadyExistsJob(
  job: Pick<JobSummary, "failure_code" | "failure_category" | "failure_message">,
) {
  return (
    job.failure_code === "backup_already_exists"
    || (job.failure_category === "replacement_failed" && /backup file already exists/i.test(job.failure_message ?? ""))
  );
}

function hasAvailableBackupForRetry(
  job: Pick<JobSummary, "original_backup_path" | "backup_deleted_at" | "backup_restored_at">,
) {
  return Boolean(job.original_backup_path && !job.backup_deleted_at && !job.backup_restored_at);
}

function isRetryableInterruptedForQueueClear(job: JobSummary) {
  return (
    normalisedJobStatus(job) === "interrupted"
    && job.interruption_retryable
    && job.assigned_worker_id == null
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

function skippedReason(job: Pick<JobSummary, "skipped_reason" | "failure_message" | "analysis_payload">) {
  return job.skipped_reason
    ?? job.failure_message
    ?? job.analysis_payload?.summary
    ?? "No replacement work was required by the active processing policy.";
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
        ["failed", "interrupted", "cancelled", "manual_review", "skipped"].includes(job.status) ||
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
    cancelled: 5,
    manual_review: 6,
    skipped: 7,
    completed: 8,
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

function jobBadge(job: JobSummary | JobDetail) {
  const status = displayJobStatus(job);
  return {
    label: "Job",
    value: titleCase(status.replace(/_/g, " ")),
    tone: jobStatusTone(job),
    title: jobStatusExplanation(job),
  };
}

function workerBadge(job: JobSummary | JobDetail) {
  const status = normalisedJobStatus(job);
  if (status === "running" && job.worker_name) {
    return {
      label: "Worker",
      value: `Running on ${job.worker_name}`,
      tone: "info" as const,
      title: "The worker currently executing this job.",
    };
  }
  if (job.worker_name || job.assigned_worker_id) {
    return {
      label: "Worker",
      value: job.worker_name ?? `Assigned ${shortId(job.assigned_worker_id ?? "")}`,
      tone: "neutral" as const,
      title: "The worker assigned to this job.",
    };
  }
  return {
    label: "Worker",
    value: status === "pending" ? "Waiting" : "Unassigned",
    tone: status === "pending" ? "warning" as const : "neutral" as const,
    title: status === "pending" ? "Waiting for an eligible worker." : "No worker is assigned.",
  };
}

function reviewBadge(job: JobSummary | JobDetail) {
  if (job.tracked_file_is_protected) {
    return {
      label: "Review",
      value: "Protected",
      tone: "warning" as const,
      title: "This file is protected and requires explicit review approval before replacement.",
    };
  }
  if (job.requires_review || job.status === "manual_review") {
    return {
      label: "Review",
      value: titleCase(job.review_status ?? "Needs review"),
      tone: "warning" as const,
      title: "The job is held for review before processing can continue.",
    };
  }
  return {
    label: "Review",
    value: "Clear",
    tone: "success" as const,
    title: "No review hold is recorded for this job.",
  };
}

function backendBadge(job: JobSummary | JobDetail) {
  if (job.backend_fallback_used) {
    return {
      label: "Backend",
      value: "CPU fallback",
      tone: "warning" as const,
      title: job.backend_selection_reason ?? "The requested backend was unavailable and the job used CPU fallback.",
    };
  }
  const backend = job.actual_execution_backend ?? job.requested_execution_backend;
  return {
    label: "Backend",
    value: formatBackendLabel(backend),
    tone: backend ? "neutral" as const : "warning" as const,
    title: backend ? "Requested or actual execution backend." : "No backend has been selected yet.",
  };
}

function scheduleBadge(job: JobSummary | JobDetail) {
  if (job.status === "scheduled") {
    return {
      label: "Schedule",
      value: "Waiting",
      tone: "warning" as const,
      title: job.schedule_summary
        ? `Waiting for schedule window: ${job.schedule_summary}.`
        : "Waiting for an allowed schedule window.",
    };
  }
  return {
    label: "Schedule",
    value: "Now",
    tone: "neutral" as const,
    title: "No schedule window is currently holding this job.",
  };
}

function jobStatusExplanation(job: JobSummary | JobDetail) {
  const status = normalisedJobStatus(job);
  if (status === "pending") {
    return "Queued and waiting for an eligible worker.";
  }
  if (status === "scheduled") {
    return "Waiting for its schedule window.";
  }
  if (status === "running") {
    return "Currently executing on a worker.";
  }
  if (status === "completed") {
    return "Execution, verification, and replacement completed successfully.";
  }
  if (status === "cancelled") {
    return "Cancelled by an operator. Processed-file state was not updated.";
  }
  if (status === "manual_review") {
    return "Held for manual review before further processing.";
  }
  if (status === "failed") {
    return job.failure_message ?? "The job failed.";
  }
  if (status === "skipped") {
    return skippedReason(job);
  }
  return "Job lifecycle status.";
}

function statusToneForValue(value: string): "neutral" | "info" | "success" | "warning" | "danger" {
  if (["passed", "succeeded", "completed", "success"].includes(value)) {
    return "success";
  }
  if (["failed", "error"].includes(value)) {
    return "danger";
  }
  if (["pending", "skipped", "not_required"].includes(value)) {
    return "warning";
  }
  return "neutral";
}

function jobStatusTone(job: JobStatusWithFailureCategory): "neutral" | "info" | "success" | "warning" | "danger" | "active" {
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
  return job.status === "cancelled" || (job.status === "interrupted" && job.failure_category === "cancelled_by_operator");
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
      initiallyOpen: items.some((item) => item.status === "running" || item.status === "pending" || isProblemJob(item)),
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

function jobMediaInfoItems(job: JobSummary) {
  const parts: string[] = [];
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
  return parts;
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
    intel_qsv: "Intel QSV",
    intel_vaapi: "Intel VAAPI",
    intel_auto: "Intel auto",
    intel_igpu: "Intel auto",
    prefer_intel_igpu: "Intel auto",
    qsv: "Intel QSV",
    vaapi: "Intel VAAPI",
    nvidia_gpu: "NVIDIA",
    prefer_nvidia_gpu: "NVIDIA",
    amd_gpu: "AMD",
    prefer_amd_gpu: "AMD",
  }[value] ?? value.replace(/_/g, " ");
}

function formatBackupPolicy(value: string | null | undefined) {
  if (value === "keep_for_1_day") {
    return "Keep for 1 day";
  }
  if (value === "delete_after_success") {
    return "Delete after success";
  }
  if (value === "no_backup") {
    return "No backup after success";
  }
  return "Keep backup";
}
