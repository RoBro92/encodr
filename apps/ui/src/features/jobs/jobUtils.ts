import { AudioStreamDecision, FileSummary, JobDetail, JobSummary, RetryJobPayload, SubtitleStreamDecision } from "../../lib/types/api";
import { formatBytes, formatDurationSeconds, titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

export function streamDecisionLabel(item: AudioStreamDecision | SubtitleStreamDecision) {
    return `#${item.index} ${item.language.toUpperCase()}`;
}

export function streamDecisionValue(item: AudioStreamDecision | SubtitleStreamDecision) {
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

export function enqueueArtworkRequest<T>(task: () => Promise<T>): Promise<T> {
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

export function jobsForTab(jobs: JobSummary[], tab: JobsTab) {
    if (tab === "active") {
    return jobs.filter(isActiveQueueJob);
    }

    if (tab === "completed") {
    return jobs.filter(isCompletedJob);
    }

    return jobs.filter(isProblemJob);
}

export function jobsTabFromQuery(tab: string | null, status: string | null): JobsTab {
    if (tab === "completed" || status === "completed" || status === "skipped") {
    return "completed";
    }

    if (tab === "problem" || ["failed", "interrupted", "cancelled", "manual_review"].includes(status ?? "")) {
    return "problem";
    }

    return "active";
}

export function tabForJob(job: JobSummary | JobDetail): JobsTab {
    if (isCompletedJob(job)) {
    return "completed";
    }

    if (isProblemJob(job)) {
    return "problem";
    }

    return "active";
}

export function tabForStatus(status: string): JobsTab {
    if (["completed", "skipped"].includes(status)) {
    return "completed";
    }

    if (["failed", "interrupted", "cancelled", "manual_review"].includes(status)) {
    return "problem";
    }

    return "active";
}

export function normaliseStatusFilter(value: string | null) {
    const allowed = new Set(JOB_STATUS_OPTIONS.map((option) => option.value));
    return value && allowed.has(value) ? value : "";
}

export function jobsRouteWithStatus(status: string) {
    return status ? `${APP_ROUTES.jobs}?status=${encodeURIComponent(status)}` : APP_ROUTES.jobs;
}

export function jobDetailRouteWithStatus(jobId: string, status: string) {
    return status
    ? `${APP_ROUTES.jobDetail(jobId)}?status=${encodeURIComponent(status)}`
    : APP_ROUTES.jobDetail(jobId);
}

export function jobsTabTitle(tab: JobsTab) {
    if (tab === "active") {
    return "Active Queue";
    }

    if (tab === "completed") {
    return "Completed Jobs";
    }

    return "Failed / Cancelled / Interrupted";
}

export function emptyTitleForTab(tab: JobsTab) {
    if (tab === "active") {
    return "No active queue";
    }

    if (tab === "completed") {
    return "No completed jobs";
    }

    return "No failed jobs";
}

export function emptyMessageForTab(tab: JobsTab) {
    if (tab === "active") {
    return "Create jobs from Library to populate the queue.";
    }

    if (tab === "completed") {
    return "Successful jobs move here after verification and replacement finish.";
    }

    return "Failed, cancelled, interrupted, and review-held jobs will appear here.";
}

export function isActiveQueueJob(job: JobSummary) {
    return ["pending", "scheduled", "running"].includes(normalisedJobStatus(job));
}

export function isCompletedJob(job: JobSummary) {
    return ["completed", "skipped"].includes(normalisedJobStatus(job));
}

export function isProblemJob(job: JobSummary) {
    return ["failed", "interrupted", "cancelled", "manual_review"].includes(normalisedJobStatus(job));
}

export function canRecoverWithStripOnly(job: JobSummary | JobDetail) {
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

export function problemSelectionErrorKeys(jobs: JobSummary[]) {
    return [...new Set(jobs.map(problemErrorKey))];
}

export function problemErrorKey(job: Pick<JobSummary, "status" | "failure_code" | "failure_category" | "failure_message" | "skipped_reason">) {
    const code = job.failure_code ?? job.failure_category ?? "unknown";
    const message = normaliseProblemMessage(job.failure_message ?? job.skipped_reason ?? "");
    return `${code}:${message}`;
}

export function normaliseProblemMessage(value: string) {
    return value.trim().replace(/\s+/g, " ").toLowerCase();
}

export function isBackupAlreadyExistsJob(job: Pick<JobSummary, "failure_code" | "failure_category" | "failure_message">) {
    return (
    job.failure_code === "backup_already_exists"
    || (job.failure_category === "replacement_failed" && /backup file already exists/i.test(job.failure_message ?? ""))
    );
}

export function hasAvailableBackupForRetry(job: Pick<JobSummary, "original_backup_path" | "backup_deleted_at" | "backup_restored_at">) {
    return Boolean(job.original_backup_path && !job.backup_deleted_at && !job.backup_restored_at);
}

export function isRetryableInterruptedForQueueClear(job: JobSummary) {
    return (
    normalisedJobStatus(job) === "interrupted"
    && job.interruption_retryable
    && job.assigned_worker_id == null
    );
}

export function deduplicateTrackedFiles(items: FileSummary[]) {
    const seen = new Set<string>();
    return items.filter((item) => {
    if (seen.has(item.id)) {
      return false;
    }
    seen.add(item.id);
    return true;
    });
}

export function formatTrackedFileOption(file: FileSummary) {
    return `${file.source_filename} — ${file.source_directory}`;
}

export function jobPrimaryLabel(job: Pick<JobSummary, "source_filename" | "tracked_file_id">, files: FileSummary[]) {
    if (job.source_filename) {
    return job.source_filename;
    }

    const trackedFile = files.find((item) => item.id === job.tracked_file_id);
    return trackedFile ? trackedFile.source_filename : `Tracked file ${shortId(job.tracked_file_id)}`;
}

export function jobContextPathLabel(job: Pick<JobSummary, "source_path" | "tracked_file_id">) {
    return job.source_path ?? `Tracked file ${shortId(job.tracked_file_id)}`;
}

export function replacementSummary(job: {
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

export function skippedReason(job: Pick<JobSummary, "skipped_reason" | "failure_message" | "analysis_payload">) {
    return job.skipped_reason
    ?? job.failure_message
    ?? job.analysis_payload?.summary
    ?? "No replacement work was required by the active processing policy.";
}

export function shortId(value: string) {
    return value.slice(0, 8);
}

export function truncate(value: string, max: number) {
    if (value.length <= max) {
    return value;
    }

    return `${value.slice(0, max - 1)}…`;
}

export function summariseJobs(jobs: Array<{
    status: string;
    requires_review: boolean;
    tracked_file_is_protected: boolean | null;
    }>) {
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

export function sortJobsForDisplay(jobs: JobSummary[]) {
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

export function canCancelJob(job: Pick<JobSummary, "id" | "status" | "assigned_worker_id" | "job_kind">, localWorkerId: string | null) {
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

export function normalisedJobStatus(job: JobStatusWithFailureCategory) {
    return isOperatorCancelled(job) ? "cancelled" : job.status;
}

export function displayJobStatus(job: JobStatusWithFailureCategory) {
    return normalisedJobStatus(job);
}

export function formatStatusLabel(value: string) {
    return value.replace(/_/g, " ").toUpperCase();
}

export function jobBadge(job: JobSummary | JobDetail) {
    const status = displayJobStatus(job);
    return {
    label: "Job",
    value: titleCase(status.replace(/_/g, " ")),
    tone: jobStatusTone(job),
    title: jobStatusExplanation(job),
    };
}

export function workerBadge(job: JobSummary | JobDetail) {
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

export function reviewBadge(job: JobSummary | JobDetail) {
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

export function backendBadge(job: JobSummary | JobDetail) {
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

export function scheduleBadge(job: JobSummary | JobDetail) {
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

export function jobStatusExplanation(job: JobSummary | JobDetail) {
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

export function statusToneForValue(value: string): "neutral" | "info" | "success" | "warning" | "danger" {
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

export function jobStatusTone(job: JobStatusWithFailureCategory): "neutral" | "info" | "success" | "warning" | "danger" | "active" {
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

export function isOperatorCancelled(job: JobStatusWithFailureCategory) {
    return job.status === "cancelled" || (job.status === "interrupted" && job.failure_category === "cancelled_by_operator");
}

export function jobProgressTone(job: JobStatusWithFailureCategory, stalled: boolean) {
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

export function describeJobProgress(job: Pick<
    JobSummary,
    | "progress_stage"
    | "progress_percent"
    | "progress_updated_at"
    | "status"
    | "failure_category"
    | "worker_name"
    | "job_kind"
    >) {
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

    const percentLabel = status === "scheduled"
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
    const detail = stalled && staleAgeSeconds != null
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

export function staleProgressAgeSeconds(progressUpdatedAt: string | null) {
    if (!progressUpdatedAt) {
    return null;
    }

    const updatedAt = Date.parse(progressUpdatedAt);
    if (Number.isNaN(updatedAt)) {
    return null;
    }

    return Math.max(0, Math.round((Date.now() - updatedAt) / 1000));
}

export function groupJobsByWorker(jobs: JobSummary[]): JobWorkerGroup[] {
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

export function sumNullable(values: Array<number | null>) {
    const present = values.filter((value): value is number => typeof value === "number");
    if (present.length === 0) {
    return null;
    }

    return present.reduce((sum, value) => sum + value, 0);
}

export function formatDurationTotal(value: number | null) {
    if (value == null) {
    return "No recorded duration";
    }

    return formatDurationSeconds(value);
}

export function workerGroupStatsLabels(group: JobWorkerGroup) {
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

export function workerGroupLabel(job: JobSummary) {
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

export function jobMediaInfoItems(job: JobSummary) {
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

export function clampProgress(value: number | null) {
    if (value == null || Number.isNaN(value)) {
    return null;
    }

    return Math.max(0, Math.min(100, value));
}

export function formatPercent(value: number | null) {
    if (value == null || Number.isNaN(value)) {
    return "Not measured";
    }

    return `${value.toFixed(value >= 10 ? 0 : 1)}%`;
}

export function formatBackendLabel(value: string | null | undefined) {
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

export function formatBackupPolicy(value: string | null | undefined) {
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

export type JobsTab = "active" | "completed" | "problem";
export type ConfirmAction = "clear-queue" | null;
export type ResolveProblemAction = "retry" | "skip";
export type BackupRetryStrategy = NonNullable<RetryJobPayload["existing_backup_strategy"]>;
export type JobWorkerGroup = {
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

export const BACKUP_PAGE_SIZE = 15;
export const COMPLETED_JOB_PAGE_SIZE = 10;
export const PROBLEM_JOB_PAGE_SIZE = 10;
export const ARTWORK_CONCURRENCY_LIMIT = 4;
export const NO_ARTWORK_CACHE = new Set<string>();
export const ARTWORK_URL_CACHE = new Map<string, string>();
export const ARTWORK_QUEUE: Array<() => void> = [];
export let activeArtworkRequests = 0;
export const JOB_STATUS_OPTIONS = [
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

export type JobStatusWithFailureCategory = {
      status: string;
      failure_category?: string | null;
    };
