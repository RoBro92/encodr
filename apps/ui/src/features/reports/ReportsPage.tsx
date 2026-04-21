import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useAnalyticsMediaQuery,
  useAnalyticsOutcomesQuery,
  useAnalyticsOverviewQuery,
  useAnalyticsRecentQuery,
  useAnalyticsStorageQuery,
} from "../../lib/api/hooks";
import { formatBytes, formatDateTime, titleCase } from "../../lib/utils/format";

export function ReportsPage() {
  const overviewQuery = useAnalyticsOverviewQuery();
  const storageQuery = useAnalyticsStorageQuery();
  const outcomesQuery = useAnalyticsOutcomesQuery();
  const mediaQuery = useAnalyticsMediaQuery();
  const recentQuery = useAnalyticsRecentQuery();

  const error =
    overviewQuery.error ??
    storageQuery.error ??
    outcomesQuery.error ??
    mediaQuery.error ??
    recentQuery.error;
  const loading =
    overviewQuery.isLoading ||
    storageQuery.isLoading ||
    outcomesQuery.isLoading ||
    mediaQuery.isLoading ||
    recentQuery.isLoading;

  if (loading) {
    return <LoadingBlock label="Loading reports" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load reports" message={error.message} />;
  }

  const overview = overviewQuery.data;
  const storage = storageQuery.data;
  const outcomes = outcomesQuery.data;
  const media = mediaQuery.data;
  const recent = recentQuery.data;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Reports"
        title="Reports"
        description="Read-only analytics from file, plan, and job history."
      />

      <section className="dashboard-grid">
        <SectionCard title="Overview" subtitle="Key counts for files, jobs, and outcomes.">
          {overview ? (
            <div className="metric-grid">
              <MetricPanel label="Tracked files" value={String(overview.total_tracked_files)} />
              <MetricPanel label="Total jobs" value={String(overview.total_jobs)} />
              <MetricPanel
                label="Processed under current policy"
                value={String(overview.processed_under_current_policy_count)}
              />
              <MetricPanel label="Protected files" value={String(overview.protected_file_count)} />
              <MetricPanel label="4K files" value={String(overview.four_k_file_count)} />
            </div>
          ) : (
            <EmptyState title="No overview available" message="Analytics data has not been generated yet." />
          )}
        </SectionCard>

        <SectionCard title="Storage" subtitle="Measured size change from recorded input and output sizes.">
          {storage ? (
            <div className="metric-grid">
              <MetricPanel label="Original size observed" value={formatBytes(storage.total_original_size_bytes)} />
              <MetricPanel label="Output size observed" value={formatBytes(storage.total_output_size_bytes)} />
              <MetricPanel label="Space saved" value={formatBytes(storage.total_space_saved_bytes)} />
              <MetricPanel label="Average saved" value={formatBytes(storage.average_space_saved_bytes)} />
            </div>
          ) : null}
        </SectionCard>
      </section>

      <section className="dashboard-grid">
        <SectionCard title="Outcome breakdown" subtitle="Status and failure distribution from job history.">
          {outcomes ? (
            <div className="card-stack">
              <MetricList title="Jobs by status" items={outcomes.jobs_by_status} />
              <MetricList title="Verification outcomes" items={outcomes.verification_outcomes} />
              <MetricList title="Replacement outcomes" items={outcomes.replacement_outcomes} />
              {outcomes.top_failure_categories.length > 0 ? (
                <div className="card-stack">
                  <strong>Top failure categories</strong>
                  <div className="list-stack">
                    {outcomes.top_failure_categories.map((item) => (
                      <div key={item.category} className="list-row">
                        <div>
                          <strong>{titleCase(item.category)}</strong>
                          <p>{item.sample_message ?? "No sample message recorded."}</p>
                        </div>
                        <StatusBadge value={String(item.count)} />
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </SectionCard>

        <SectionCard title="Media summary" subtitle="Recent probe and plan trends.">
          {media ? (
            <div className="card-stack">
              <div className="metric-grid">
                <MetricPanel label="Latest probes" value={String(media.latest_probe_count)} />
                <MetricPanel label="Latest plans" value={String(media.latest_plan_count)} />
                <MetricPanel label="English audio present" value={String(media.latest_probe_english_audio_count)} />
                <MetricPanel
                  label="Forced subtitle intent"
                  value={String(media.latest_plan_forced_subtitle_intent_count)}
                />
                <MetricPanel
                  label="Surround preserved"
                  value={String(media.latest_plan_surround_preservation_intent_count)}
                />
                <MetricPanel
                  label="Atmos preserved"
                  value={String(media.latest_plan_atmos_preservation_intent_count)}
                />
              </div>
              <MetricList title="Container distribution" items={media.container_distribution} />
              <MetricList title="Video codec distribution" items={media.video_codec_distribution} />
            </div>
          ) : null}
        </SectionCard>
      </section>

      <SectionCard title="Recent activity" subtitle="Latest completed and failed outcomes.">
        {recent && (recent.recent_completed_jobs.length > 0 || recent.recent_failed_jobs.length > 0) ? (
          <div className="two-column-layout">
            <RecentList title="Recent completed" items={recent.recent_completed_jobs} />
            <RecentList title="Recent failures" items={recent.recent_failed_jobs} />
          </div>
        ) : (
          <EmptyState title="No recent activity" message="Recent outcome history will appear here once jobs have been processed." />
        )}
      </SectionCard>
    </div>
  );
}

function MetricList({
  title,
  items,
}: {
  title: string;
  items: Array<{ value: string; count: number }>;
}) {
  return (
    <div className="card-stack">
      <strong>{title}</strong>
      {items.length > 0 ? (
        <div className="badge-list">
          {items.map((item) => (
            <div key={item.value} className="metric-pill">
              <span>{titleCase(item.value)}</span>
              <strong>{item.count}</strong>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          title={`No ${title.toLowerCase()}`}
          message="The current history does not yet contain data for this section."
        />
      )}
    </div>
  );
}

function RecentList({
  title,
  items,
}: {
  title: string;
  items: Array<{
    job_id: string;
    file_name: string;
    status: string;
    action: string;
    updated_at: string;
    failure_category: string | null;
  }>;
}) {
  return (
    <div className="card-stack">
      <strong>{title}</strong>
      {items.length > 0 ? (
        <div className="list-stack">
          {items.map((item) => (
            <div key={item.job_id} className="list-row">
              <div>
                <strong>{item.file_name}</strong>
                <p>
                  {titleCase(item.action)} · {formatDateTime(item.updated_at)}
                  {item.failure_category ? ` · ${titleCase(item.failure_category)}` : ""}
                </p>
              </div>
              <StatusBadge value={item.status} />
            </div>
          ))}
        </div>
      ) : (
        <EmptyState title={`No ${title.toLowerCase()}`} message="This outcome bucket is currently empty." />
      )}
    </div>
  );
}

function MetricPanel({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="metric-panel">
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
