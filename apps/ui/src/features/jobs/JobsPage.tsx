import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
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
    useResolveFailedJobsMutation,
    useRestoreJobBackupMutation,
    useRetryJobMutation,
    useStripOnlyRecoveryMutation,
    useWorkerStatusQuery,
} from "../../lib/api/hooks";
import { formatDateTime } from "../../lib/utils/format";
import { BackupRetryModal } from "./components/BackupRetryModal";
import { BackupRow } from "./components/BackupRow";
import { ConfirmBulkActionModal } from "./components/ConfirmBulkActionModal";
import { JobArtwork, JobDetailDrawer } from "./components/JobDetailDrawer";
import { JobMetadataBadges } from "./components/JobMetadataBadges";
import { JobProgressBar } from "./components/JobProgressBar";
import { JobStatusBadgeRow } from "./components/JobStatusBadgeRow";
import { MixedProblemSelectionModal } from "./components/MixedProblemSelectionModal";
import { ResolveProblemJobsModal } from "./components/ResolveProblemJobsModal";
import { StripOnlyRecoveryModal } from "./components/StripOnlyRecoveryModal";
import { TrackedFilePicker } from "./components/TrackedFilePicker";
import { BACKUP_PAGE_SIZE, BackupRetryStrategy, canCancelJob, canRecoverWithStripOnly, COMPLETED_JOB_PAGE_SIZE, ConfirmAction, deduplicateTrackedFiles, displayJobStatus, emptyMessageForTab, emptyTitleForTab, formatStatusLabel, groupJobsByWorker, hasAvailableBackupForRetry, isActiveQueueJob, isBackupAlreadyExistsJob, isRetryableInterruptedForQueueClear, JOB_STATUS_OPTIONS, jobContextPathLabel, jobDetailRouteWithStatus, jobMediaInfoItems, jobPrimaryLabel, jobsForTab, jobsRouteWithStatus, JobsTab, jobsTabFromQuery, jobsTabTitle, jobStatusTone, normalisedJobStatus, normaliseStatusFilter, PROBLEM_JOB_PAGE_SIZE, problemSelectionErrorKeys, replacementSummary, ResolveProblemAction, shortId, skippedReason, sortJobsForDisplay, summariseJobs, tabForJob, tabForStatus, workerGroupStatsLabels } from "./jobUtils";

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
