import { ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CollapsibleSection } from "../../../components/CollapsibleSection";
import { EmptyState } from "../../../components/EmptyState";
import { KeyValueList } from "../../../components/KeyValueList";
import { LoadingBlock } from "../../../components/LoadingBlock";
import { AudioStreamDecision, FileSummary, JobDetail, SubtitleStreamDecision } from "../../../lib/types/api";
import { formatBitrate, formatBytes, formatDateTime, titleCase } from "../../../lib/utils/format";
import { APP_ROUTES } from "../../../lib/utils/routes";
import { useSession } from "../../auth/AuthProvider";
import { ARTWORK_URL_CACHE, NO_ARTWORK_CACHE, describeJobProgress, enqueueArtworkRequest, formatBackendLabel, formatBackupPolicy, formatPercent, isOperatorCancelled, jobPrimaryLabel, normalisedJobStatus, skippedReason, streamDecisionLabel, streamDecisionValue } from "../jobUtils";
import { JobProgressBar } from "./JobProgressBar";
import { JobStatusBadgeRow } from "./JobStatusBadgeRow";

export function JobDetailDrawer({
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

export function JobDrawerCallouts({ detail }: { detail: JobDetail }) {
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

export function JobDrawerCallout({
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

export function JobDrawerMetric({ label, value }: { label: string; value: ReactNode }) {
    return (
    <div className="job-drawer-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
    );
}

export function JobMetadataItem({
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

export function MutedValue({ children }: { children: ReactNode }) {
    return <span className="job-drawer-muted-value">{children}</span>;
}

export function StreamDecisionList({
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

export function JobArtwork({ jobId, title }: { jobId: string; title: string }) {
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
