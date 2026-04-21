import { Link, useParams } from "react-router-dom";
import { useMemo, useState } from "react";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { PayloadViewer } from "../../components/PayloadViewer";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useApproveReviewItemMutation,
  useClearReviewItemProtectedMutation,
  useCreateJobFromReviewItemMutation,
  useHoldReviewItemMutation,
  useRejectReviewItemMutation,
  useReplanReviewItemMutation,
  useMarkReviewItemProtectedMutation,
  useReviewItemDetailQuery,
  useReviewItemsQuery,
} from "../../lib/api/hooks";
import { formatDateTime, formatRelativeBoolean } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

export function ReviewPage() {
  const { itemId } = useParams();
  const [status, setStatus] = useState("open");
  const [protectedOnly, setProtectedOnly] = useState("");
  const [is4k, setIs4k] = useState("");
  const [recentFailuresOnly, setRecentFailuresOnly] = useState(false);
  const [decisionNote, setDecisionNote] = useState("");

  const filters = useMemo(
    () => ({
      status: status || undefined,
      protected_only: protectedOnly === "" ? undefined : protectedOnly === "true",
      is_4k: is4k === "" ? undefined : is4k === "true",
      recent_failures_only: recentFailuresOnly || undefined,
      limit: 100,
    }),
    [is4k, protectedOnly, recentFailuresOnly, status],
  );

  const itemsQuery = useReviewItemsQuery(filters);
  const detailQuery = useReviewItemDetailQuery(itemId);
  const approveMutation = useApproveReviewItemMutation();
  const rejectMutation = useRejectReviewItemMutation();
  const holdMutation = useHoldReviewItemMutation();
  const protectMutation = useMarkReviewItemProtectedMutation();
  const clearProtectedMutation = useClearReviewItemProtectedMutation();
  const replanMutation = useReplanReviewItemMutation();
  const createJobMutation = useCreateJobFromReviewItemMutation();

  const queryError = itemsQuery.error ?? detailQuery.error;
  const mutationError =
    approveMutation.error ??
    rejectMutation.error ??
    holdMutation.error ??
    protectMutation.error ??
    clearProtectedMutation.error ??
    replanMutation.error ??
    createJobMutation.error;

  if (itemsQuery.isLoading) {
    return <LoadingBlock label="Loading review items" />;
  }

  if (queryError instanceof Error) {
    return <ErrorPanel title="Unable to load review items" message={queryError.message} />;
  }

  const items = itemsQuery.data?.items ?? [];
  const detail = detailQuery.data;
  const decisionRequest = decisionNote.trim() ? { note: decisionNote.trim() } : {};
  const isActionPending =
    approveMutation.isPending ||
    rejectMutation.isPending ||
    holdMutation.isPending ||
    protectMutation.isPending ||
    clearProtectedMutation.isPending ||
    replanMutation.isPending ||
    createJobMutation.isPending;
  const metrics = summariseReviewItems(items);

  async function handleDecision(
    action:
      | "approve"
      | "reject"
      | "hold"
      | "mark_protected"
      | "clear_protected"
      | "replan"
      | "create_job",
  ) {
    if (!detail) {
      return;
    }

    const payload = { itemId: detail.id, request: decisionRequest };
    switch (action) {
      case "approve":
        await approveMutation.mutateAsync(payload);
        break;
      case "reject":
        await rejectMutation.mutateAsync(payload);
        break;
      case "hold":
        await holdMutation.mutateAsync(payload);
        break;
      case "mark_protected":
        await protectMutation.mutateAsync(payload);
        break;
      case "clear_protected":
        await clearProtectedMutation.mutateAsync(payload);
        break;
      case "replan":
        await replanMutation.mutateAsync(payload);
        break;
      case "create_job":
        await createJobMutation.mutateAsync(payload);
        break;
      default:
        return;
    }
    setDecisionNote("");
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Review"
        title="Review"
        description="See why automation paused, inspect the latest context, then take a decision."
      />

      {mutationError instanceof Error ? (
        <ErrorPanel title="Review action failed" message={mutationError.message} />
      ) : null}

      <section className="metric-grid">
        <div className="metric-panel">
          <span className="metric-label">Items in view</span>
          <strong>{metrics.total}</strong>
          <span className="metric-subtle">Current review queue</span>
        </div>
        <div className="metric-panel">
          <span className="metric-label">Open</span>
          <strong>{metrics.open}</strong>
          <span className="metric-subtle">Awaiting a decision</span>
        </div>
        <div className="metric-panel">
          <span className="metric-label">Protected</span>
          <strong>{metrics.protected}</strong>
          <span className="metric-subtle">Planner or operator protected</span>
        </div>
        <div className="metric-panel">
          <span className="metric-label">Held</span>
          <strong>{metrics.held}</strong>
          <span className="metric-subtle">Paused for later follow-up</span>
        </div>
      </section>

      <section className={`jobs-review-layout${items.length === 0 || (!detail && !(itemId && detailQuery.isLoading)) ? " jobs-review-layout-single" : ""}`}>
        <div className="list-detail-stack">
          <SectionCard title="Filters" subtitle="Focus on the items that need a decision now.">
            <div className="filter-grid filter-grid-tight">
              <label className="field">
                <span>Review status</span>
                <select value={status} onChange={(event) => setStatus(event.target.value)}>
                  <option value="">Any</option>
                  <option value="open">Open</option>
                  <option value="approved">Approved</option>
                  <option value="held">Held</option>
                  <option value="rejected">Rejected</option>
                  <option value="resolved">Resolved</option>
                </select>
              </label>
              <label className="field">
                <span>Protection</span>
                <select value={protectedOnly} onChange={(event) => setProtectedOnly(event.target.value)}>
                  <option value="">Any</option>
                  <option value="true">Protected only</option>
                  <option value="false">Unprotected only</option>
                </select>
              </label>
              <label className="field">
                <span>Resolution</span>
                <select value={is4k} onChange={(event) => setIs4k(event.target.value)}>
                  <option value="">Any</option>
                  <option value="true">4K only</option>
                  <option value="false">Non-4K only</option>
                </select>
              </label>
              <label className="field checkbox-field">
                <input
                  type="checkbox"
                  checked={recentFailuresOnly}
                  onChange={(event) => setRecentFailuresOnly(event.target.checked)}
                />
                <span>Recent failures only</span>
              </label>
            </div>
          </SectionCard>

          <SectionCard title="Inbox" subtitle={`${items.length} item${items.length === 1 ? "" : "s"} in view`}>
            {items.length === 0 ? (
              <EmptyState
                title="No review items"
                message="Nothing needs a manual decision right now."
              />
            ) : (
              <div className="record-list" role="list" aria-label="Review items list">
                {items.map((item) => {
                  const isActive = item.id === itemId;
                  return (
                    <Link
                      key={item.id}
                      className={`record-list-item${isActive ? " record-list-item-active" : ""}`}
                      to={APP_ROUTES.reviewDetail(item.id)}
                    >
                      <div className="record-list-main">
                        <div className="record-list-heading">
                          <strong>{item.tracked_file.source_filename}</strong>
                          <span>{item.tracked_file.source_directory}</span>
                        </div>
                        <div className="badge-row">
                          <StatusBadge value={item.review_status} />
                          <StatusBadge value={item.confidence ?? "unknown"} />
                          {item.requires_review ? <StatusBadge value="manual_review" /> : null}
                          {item.protected_state.is_protected ? <StatusBadge value="protected" /> : null}
                        </div>
                      </div>
                      <div className="record-list-meta">
                        <span className="record-list-kicker">{reviewPriorityLabel(item)}</span>
                        <span>{formatDateTime(item.latest_job_at ?? item.latest_plan_at ?? item.latest_probe_at)}</span>
                        <span className="record-list-emphasis">
                          {summariseReasons(item.reasons, item.warnings)}
                        </span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </SectionCard>
        </div>

        {itemId && detailQuery.isLoading ? (
          <SectionCard title="Selected item" subtitle="Loading the latest decision context.">
            <LoadingBlock label="Loading review detail" />
          </SectionCard>
        ) : detail ? (
          <SectionCard
            title="Selected item"
            subtitle={detail.tracked_file.source_filename}
          >
            <div className="card-stack">
              <section className="review-reasons-grid">
                <div className="review-alert-panel review-alert-danger">
                  <span className="metric-label">Needs review because</span>
                  {detail.reasons.length > 0 ? (
                    <ul className="plain-list">
                      {detail.reasons.map((reason) => (
                        <li key={`reason-${reason.code}`}>
                          <strong>{reason.message}</strong>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted-copy">No explicit review reasons are attached.</p>
                  )}
                </div>
                <div className="review-alert-panel review-alert-warning">
                  <span className="metric-label">Warnings</span>
                  {detail.warnings.length > 0 ? (
                    <ul className="plain-list">
                      {detail.warnings.map((warning) => (
                        <li key={`warning-${warning.code}`}>
                          <strong>{warning.message}</strong>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted-copy">No warnings recorded.</p>
                  )}
                </div>
              </section>

              <div className="badge-row">
                <StatusBadge value={detail.review_status} />
                <StatusBadge value={detail.confidence ?? "unknown"} />
                {detail.requires_review ? <StatusBadge value="manual_review" /> : null}
                {detail.protected_state.is_protected ? <StatusBadge value="protected" /> : null}
                {detail.latest_job ? <StatusBadge value={detail.latest_job.status} /> : null}
              </div>

              <KeyValueList
                items={[
                  { label: "Source path", value: detail.source_path },
                  { label: "Protected", value: formatRelativeBoolean(detail.protected_state.is_protected) },
                  { label: "Protected source", value: formatProtectedSource(detail.protected_state.source) },
                  {
                    label: "Latest decision",
                    value: detail.latest_decision
                      ? `${detail.latest_decision.decision_type} by ${detail.latest_decision.created_by_username}`
                      : "No decision recorded",
                  },
                  {
                    label: "Latest activity",
                    value: formatDateTime(detail.latest_job_at ?? detail.latest_plan_at ?? detail.latest_probe_at),
                  },
                ]}
              />

              <section className="decision-panel">
                <div className="decision-panel-copy">
                  <span className="metric-label">Decision</span>
                  <strong>Choose the next step</strong>
                  <span className="metric-subtle">
                    Approval, rejection, protection, replan, and job creation stay on the same backend actions.
                  </span>
                </div>
                <label className="field">
                  <span>Operator note</span>
                  <textarea
                    rows={3}
                    value={decisionNote}
                    onChange={(event) => setDecisionNote(event.target.value)}
                    placeholder="Add context for the next operator or audit trail"
                  />
                </label>
                <div className="decision-button-grid">
                  <button
                    className="button button-primary"
                    type="button"
                    onClick={() => void handleDecision("approve")}
                    disabled={isActionPending || !detail.requires_review}
                  >
                    Approve
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void handleDecision("hold")}
                    disabled={isActionPending}
                  >
                    Hold
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void handleDecision("reject")}
                    disabled={isActionPending}
                  >
                    Reject
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void handleDecision("mark_protected")}
                    disabled={isActionPending || detail.protected_state.operator_protected}
                  >
                    Mark protected
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void handleDecision("clear_protected")}
                    disabled={isActionPending || !detail.protected_state.operator_protected}
                  >
                    Clear protected
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void handleDecision("replan")}
                    disabled={isActionPending}
                  >
                    Replan
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void handleDecision("create_job")}
                    disabled={isActionPending || detail.review_status !== "approved"}
                  >
                    Create job
                  </button>
                </div>
              </section>

              <CollapsibleSection
                title="Show protection details"
                subtitle="Planner and operator protection are kept separate."
              >
                <KeyValueList
                  items={[
                    { label: "Planner protected", value: formatRelativeBoolean(detail.protected_state.planner_protected) },
                    { label: "Operator protected", value: formatRelativeBoolean(detail.protected_state.operator_protected) },
                    { label: "Reason codes", value: detail.protected_state.reason_codes.join(", ") || "None" },
                    { label: "Operator note", value: detail.protected_state.note ?? "None" },
                    { label: "Updated by", value: detail.protected_state.updated_by_username ?? "Not recorded" },
                    { label: "Updated at", value: formatDateTime(detail.protected_state.updated_at) },
                  ]}
                />
              </CollapsibleSection>

              {detail.latest_plan ? (
                <CollapsibleSection
                  title="Show latest plan"
                  subtitle="Planner action, confidence, and profile details."
                >
                  <KeyValueList
                    items={[
                      { label: "Action", value: <StatusBadge value={detail.latest_plan.action} /> },
                      { label: "Confidence", value: <StatusBadge value={detail.latest_plan.confidence} /> },
                      { label: "Policy version", value: detail.latest_plan.policy_version },
                      { label: "Profile", value: detail.latest_plan.profile_name ?? "Default policy" },
                    ]}
                  />
                </CollapsibleSection>
              ) : null}

              {detail.latest_job ? (
                <CollapsibleSection
                  title="Advanced latest job details"
                  subtitle="Latest execution status and verification outcome."
                >
                  <div className="card-stack">
                    <KeyValueList
                      items={[
                        { label: "Status", value: <StatusBadge value={detail.latest_job.status} /> },
                        { label: "Verification", value: <StatusBadge value={detail.latest_job.verification_status} /> },
                        { label: "Replacement", value: <StatusBadge value={detail.latest_job.replacement_status} /> },
                        { label: "Failure", value: detail.latest_job.failure_message ?? "None" },
                      ]}
                    />
                    <PayloadViewer
                      payload={{
                        latest_plan: detail.latest_plan,
                        latest_job: detail.latest_job,
                        protected_state: detail.protected_state,
                      }}
                    />
                  </div>
                </CollapsibleSection>
              ) : null}
            </div>
          </SectionCard>
        ) : null}
      </section>
    </div>
  );
}

function formatProtectedSource(value: string) {
  return value.split("_").join(" ");
}

function summariseReviewItems(
  items: Array<{
    review_status: string;
    protected_state: { is_protected: boolean };
  }>,
) {
  return {
    total: items.length,
    open: items.filter((item) => item.review_status === "open").length,
    protected: items.filter((item) => item.protected_state.is_protected).length,
    held: items.filter((item) => item.review_status === "held").length,
  };
}

function reviewPriorityLabel(item: {
  protected_state: { is_protected: boolean };
  requires_review: boolean;
  latest_job: { status: string } | null;
}) {
  if (item.protected_state.is_protected) {
    return "Protected";
  }
  if (item.latest_job?.status === "failed") {
    return "Recent failure";
  }
  if (item.requires_review) {
    return "Needs decision";
  }
  return "Watch list";
}

function summariseReasons(
  reasons: Array<{ message: string }>,
  warnings: Array<{ message: string }>,
) {
  if (reasons[0]?.message) {
    return reasons[0].message;
  }
  if (warnings[0]?.message) {
    return warnings[0].message;
  }
  return "No reason details recorded";
}
