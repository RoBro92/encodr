import { JobSummary } from "../../../lib/types/api";
import { formatDurationSeconds } from "../../../lib/utils/format";
import { describeJobProgress, jobProgressTone } from "../jobUtils";

export function JobProgressBar({
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
