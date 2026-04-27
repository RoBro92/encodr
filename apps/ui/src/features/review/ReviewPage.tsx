import type { ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { PayloadViewer } from "../../components/PayloadViewer";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useApproveReviewItemMutation,
  useClearReviewItemProtectedMutation,
  useCreateJobFromReviewItemMutation,
  useExcludeReviewItemMutation,
  useHoldReviewItemMutation,
  useRejectReviewItemMutation,
  useReplanReviewItemMutation,
  useMarkReviewItemProtectedMutation,
  useReviewItemDetailQuery,
  useReviewItemsQuery,
} from "../../lib/api/hooks";
import type { ReviewItemDetail, ReviewItemSummary, ReviewReason } from "../../lib/types/api";
import { formatDateTime, formatRelativeBoolean } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

type ReviewDecisionAction =
  | "approve"
  | "reject"
  | "hold"
  | "mark_protected"
  | "clear_protected"
  | "replan"
  | "create_job"
  | "exclude";

export function ReviewPage() {
  const { itemId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState(searchParams.get("status") ?? "open");
  const [protectedOnly, setProtectedOnly] = useState("");
  const [is4k, setIs4k] = useState("");
  const [recentFailuresOnly, setRecentFailuresOnly] = useState(false);
  const [decisionNote, setDecisionNote] = useState("");
  const previousItemsRef = useRef<ReviewItemSummary[]>([]);

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
  const excludeMutation = useExcludeReviewItemMutation();

  const queryError = itemsQuery.error ?? detailQuery.error;
  const mutationError =
    approveMutation.error ??
    rejectMutation.error ??
    holdMutation.error ??
    protectMutation.error ??
    clearProtectedMutation.error ??
    replanMutation.error ??
    createJobMutation.error ??
    excludeMutation.error;

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
    createJobMutation.isPending ||
    excludeMutation.isPending;
  const metrics = summariseReviewItems(items);

  useEffect(() => {
    const queryStatus = searchParams.get("status") ?? "open";
    if (queryStatus !== status) {
      setStatus(queryStatus);
    }
  }, [searchParams, status]);

  useEffect(() => {
    if (itemsQuery.isLoading) {
      return;
    }
    if (!itemId) {
      previousItemsRef.current = items;
      return;
    }
    if (items.some((item) => item.id === itemId)) {
      previousItemsRef.current = items;
      return;
    }
    const previousItems = previousItemsRef.current;
    const previousIndex = previousItems.findIndex((item) => item.id === itemId);
    const nextItem = items[previousIndex] ?? items[previousIndex - 1] ?? items[0] ?? null;
    setDecisionNote("");
    navigate(nextItem ? APP_ROUTES.reviewDetail(nextItem.id) : APP_ROUTES.review, { replace: true });
    previousItemsRef.current = items;
  }, [itemId, items, itemsQuery.isLoading, navigate]);

  if (itemsQuery.isLoading) {
    return <LoadingBlock label="Loading review items" />;
  }

  if (queryError instanceof Error) {
    return <ErrorPanel title="Unable to load review items" message={queryError.message} />;
  }

  async function handleDecision(
    action: ReviewDecisionAction,
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
      case "exclude":
        await excludeMutation.mutateAsync(payload);
        break;
      default:
        return;
    }
    setDecisionNote("");
  }

  function closeDrawer() {
    setDecisionNote("");
    navigate(APP_ROUTES.review);
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

      <section className="metrics-card-grid" aria-label="Review metrics">
        <div className="metrics-card-item">
          <span className="metrics-card-label">Items in view</span>
          <strong className="metrics-card-value">{metrics.total}</strong>
        </div>
        <div className="metrics-card-item">
          <span className="metrics-card-label">Open</span>
          <strong className="metrics-card-value">{metrics.open}</strong>
        </div>
        <div className="metrics-card-item">
          <span className="metrics-card-label">Protected</span>
          <strong className="metrics-card-value">{metrics.protected}</strong>
        </div>
        <div className="metrics-card-item">
          <span className="metrics-card-label">Held</span>
          <strong className="metrics-card-value">{metrics.held}</strong>
        </div>
      </section>

      <section className="review-workspace">
        <div className="list-detail-stack">
          <SectionCard title="Filters" subtitle="Focus on the items that need a decision now.">
            <div className="review-filter-row">
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
                  className="review-filter-checkbox h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-600"
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
              <div className="record-list review-inbox-list" role="list" aria-label="Review items list">
                {items.map((item) => {
                  const isActive = item.id === itemId;
                  return (
                    <Link
                      key={item.id}
                      className={`review-inbox-item${isActive ? " review-inbox-item-active" : ""}`}
                      to={APP_ROUTES.reviewDetail(item.id)}
                    >
                      <div className="review-inbox-main">
                        <div className="review-inbox-heading">
                          <strong>{item.tracked_file.source_filename}</strong>
                          <span title={item.source_path}>{item.source_path}</span>
                        </div>
                        <p className="review-inbox-reason">
                          {summariseReasons(item.reasons, item.warnings)}
                        </p>
                        <div className="badge-row">
                          <StatusBadge value={item.review_status} />
                          <StatusBadge value={item.confidence ?? "unknown"} />
                          {item.requires_review ? <StatusBadge value="manual_review" /> : null}
                          {item.protected_state.is_protected ? <StatusBadge value="protected" /> : null}
                        </div>
                      </div>
                      <div className="review-inbox-meta">
                        <span className="record-list-kicker">{reviewPriorityLabel(item)}</span>
                        <span>{formatDateTime(item.latest_job_at ?? item.latest_plan_at ?? item.latest_probe_at)}</span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </SectionCard>
        </div>
      </section>

      {itemId ? (
        <ReviewDetailDrawer
          detail={detail}
          isLoading={detailQuery.isLoading}
          decisionNote={decisionNote}
          isActionPending={isActionPending}
          onClose={closeDrawer}
          onDecision={(action) => void handleDecision(action)}
          onDecisionNoteChange={setDecisionNote}
        />
      ) : null}
    </div>
  );
}

function ReviewDetailDrawer({
  detail,
  isLoading,
  decisionNote,
  isActionPending,
  onClose,
  onDecision,
  onDecisionNoteChange,
}: {
  detail: ReviewItemDetail | undefined;
  isLoading: boolean;
  decisionNote: string;
  isActionPending: boolean;
  onClose: () => void;
  onDecision: (action: ReviewDecisionAction) => void;
  onDecisionNoteChange: (value: string) => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

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

  const title = detail?.tracked_file.source_filename ?? "Selected item";

  return (
    <>
      <button
        className="review-drawer-backdrop"
        type="button"
        aria-label="Close review detail"
        onClick={onClose}
      />
      <aside className="review-drawer-panel" role="dialog" aria-modal="true" aria-labelledby="review-drawer-title">
        <header className="review-drawer-header">
          <div className="review-drawer-title">
            <span className="metric-label">Selected item</span>
            <h2 id="review-drawer-title">{title}</h2>
            {detail ? (
              <div className="badge-row">
                <StatusBadge value={detail.review_status} />
                <StatusBadge value={detail.confidence ?? "unknown"} />
                {detail.requires_review ? <StatusBadge value="manual_review" /> : null}
                {detail.protected_state.is_protected ? <StatusBadge value="protected" /> : null}
                {detail.latest_job ? <StatusBadge value={detail.latest_job.status} /> : null}
              </div>
            ) : null}
          </div>
          <button
            ref={closeButtonRef}
            className="review-drawer-close"
            type="button"
            aria-label="Close selected review item"
            onClick={onClose}
          >
            X
          </button>
        </header>

        <div className="review-drawer-body">
          {isLoading ? (
            <LoadingBlock label="Loading review detail" />
          ) : detail ? (
            <div className="card-stack">
              <section className="review-alert-stack" aria-label="Review alerts">
                <ReviewAlert
                  tone="danger"
                  title="Needs review because"
                  items={detail.reasons}
                  emptyMessage="No explicit review reasons are attached."
                />
                <ReviewAlert
                  tone="warning"
                  title="Warnings"
                  items={detail.warnings}
                  emptyMessage="No warnings recorded."
                />
              </section>

              <section className="review-metadata-grid" aria-label="Review metadata">
                <ReviewMetadataItem
                  label="Source path"
                  value={<span className="truncate-text" title={detail.source_path}>{detail.source_path}</span>}
                  className="review-metadata-item-wide review-source-path"
                />
                <ReviewMetadataItem label="Protected" value={formatRelativeBoolean(detail.protected_state.is_protected)} />
                <ReviewMetadataItem label="Protected source" value={formatProtectedSource(detail.protected_state.source)} />
                <ReviewMetadataItem
                  label="Latest decision"
                  value={
                    detail.latest_decision
                      ? `${detail.latest_decision.decision_type} by ${detail.latest_decision.created_by_username}`
                      : "No decision recorded"
                  }
                />
                <ReviewMetadataItem
                  label="Latest activity"
                  value={formatDateTime(detail.latest_job_at ?? detail.latest_plan_at ?? detail.latest_probe_at)}
                />
              </section>

              <label className="field review-operator-note">
                <span>Operator note</span>
                <textarea
                  rows={2}
                  value={decisionNote}
                  onChange={(event) => onDecisionNoteChange(event.target.value)}
                  placeholder="Add context for the next operator or audit trail"
                />
              </label>

              <CollapsibleSection
                title="Show protection details"
                subtitle="Planner and operator protection are kept separate."
              >
                <section className="review-metadata-grid" aria-label="Protection details">
                  <ReviewMetadataItem label="Planner protected" value={formatRelativeBoolean(detail.protected_state.planner_protected)} />
                  <ReviewMetadataItem label="Operator protected" value={formatRelativeBoolean(detail.protected_state.operator_protected)} />
                  <ReviewMetadataItem label="Reason codes" value={detail.protected_state.reason_codes.join(", ") || "None"} />
                  <ReviewMetadataItem label="Operator note" value={detail.protected_state.note ?? "None"} />
                  <ReviewMetadataItem label="Updated by" value={detail.protected_state.updated_by_username ?? "Not recorded"} />
                  <ReviewMetadataItem label="Updated at" value={formatDateTime(detail.protected_state.updated_at)} />
                </section>
              </CollapsibleSection>

              {detail.latest_plan ? (
                <CollapsibleSection
                  title="Show latest plan"
                  subtitle="Planner action, confidence, and profile details."
                >
                  <section className="review-metadata-grid" aria-label="Latest plan">
                    <ReviewMetadataItem label="Action" value={<StatusBadge value={detail.latest_plan.action} />} />
                    <ReviewMetadataItem label="Confidence" value={<StatusBadge value={detail.latest_plan.confidence} />} />
                    <ReviewMetadataItem label="Policy version" value={detail.latest_plan.policy_version} />
                    <ReviewMetadataItem label="Profile" value={detail.latest_plan.profile_name ?? "Default policy"} />
                  </section>
                </CollapsibleSection>
              ) : null}

              {detail.latest_job ? (
                <CollapsibleSection
                  title="Advanced latest job details"
                  subtitle="Latest execution status and verification outcome."
                >
                  <div className="card-stack">
                    <section className="review-metadata-grid" aria-label="Latest job details">
                      <ReviewMetadataItem label="Status" value={<StatusBadge value={detail.latest_job.status} />} />
                      <ReviewMetadataItem label="Verification" value={<StatusBadge value={detail.latest_job.verification_status} />} />
                      <ReviewMetadataItem label="Replacement" value={<StatusBadge value={detail.latest_job.replacement_status} />} />
                      <ReviewMetadataItem label="Failure" value={detail.latest_job.failure_message ?? "None"} />
                    </section>
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
          ) : (
            <EmptyState title="No item selected" message="Choose a review item to inspect its decision context." />
          )}
        </div>

        {detail ? (
          <footer className="review-drawer-footer">
            <div className="review-action-bar">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => onDecision("hold")}
                disabled={isActionPending}
              >
                Hold
              </button>
              <button
                className="button button-secondary"
                type="button"
                onClick={() => onDecision("reject")}
                disabled={isActionPending}
              >
                Reject
              </button>
              <button
                className="button button-secondary"
                type="button"
                onClick={() => onDecision("mark_protected")}
                disabled={isActionPending || detail.protected_state.operator_protected}
              >
                Mark protected
              </button>
              <button
                className="button button-secondary"
                type="button"
                onClick={() => onDecision("clear_protected")}
                disabled={isActionPending || !detail.protected_state.operator_protected}
              >
                Clear protected
              </button>
              <button
                className="button button-secondary"
                type="button"
                onClick={() => onDecision("exclude")}
                disabled={isActionPending}
              >
                Exclude from future processing
              </button>
              <button
                className="button button-primary review-primary-action"
                type="button"
                onClick={() => onDecision("approve")}
                disabled={isActionPending || !detail.requires_review}
              >
                Approve
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={() => onDecision("replan")}
                disabled={isActionPending}
              >
                Replan
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={() => onDecision("create_job")}
                disabled={isActionPending || detail.review_status !== "approved"}
              >
                Create job
              </button>
            </div>
          </footer>
        ) : null}
      </aside>
    </>
  );
}

function ReviewAlert({
  tone,
  title,
  items,
  emptyMessage,
}: {
  tone: "danger" | "warning";
  title: string;
  items: ReviewReason[];
  emptyMessage: string;
}) {
  return (
    <div className={`review-callout review-callout-${tone}`}>
      <span className="metric-label">{title}</span>
      {items.length > 0 ? (
        <ul className="plain-list">
          {items.map((item) => (
            <li key={`${tone}-${item.code}`}>
              <span>{item.message}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted-copy">{emptyMessage}</p>
      )}
    </div>
  );
}

function ReviewMetadataItem({ label, value, className }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div className={`review-metadata-item${className ? ` ${className}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
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
