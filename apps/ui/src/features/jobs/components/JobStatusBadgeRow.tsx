import { JobDetail, JobSummary } from "../../../lib/types/api";
import { titleCase } from "../../../lib/utils/format";
import { backendBadge, jobBadge, reviewBadge, scheduleBadge, statusToneForValue, workerBadge } from "../jobUtils";
import { ExplainedStatusBadge } from "./ExplainedStatusBadge";

export function JobStatusBadgeRow({
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
