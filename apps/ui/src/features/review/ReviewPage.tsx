import { Link, useParams } from "react-router-dom";
import { useMemo, useState } from "react";

import { DataTable } from "../../components/DataTable";
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
        eyebrow="Manual Review"
        title="Manual review queue"
        description="Inspect ambiguous or protected files, review why automation paused, and take explicit operator decisions."
      />

      {mutationError instanceof Error ? (
        <ErrorPanel title="Review action failed" message={mutationError.message} />
      ) : null}

      <section className="dashboard-grid">
        <SectionCard title="Filters" subtitle="Focus on open review items, protected files, and recent failures.">
          <div className="filter-grid">
            <label className="field">
              <span>Status</span>
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
              <span>Protected</span>
              <select value={protectedOnly} onChange={(event) => setProtectedOnly(event.target.value)}>
                <option value="">Any</option>
                <option value="true">Protected only</option>
                <option value="false">Unprotected only</option>
              </select>
            </label>
            <label className="field">
              <span>4K</span>
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
      </section>

      <section className="two-column-layout">
        <SectionCard title="Review items" subtitle={`${items.length} result${items.length === 1 ? "" : "s"}`}>
          <DataTable
            items={items}
            rowKey={(item) => item.id}
            empty={
              <EmptyState
                title="No review items"
                message="Open manual-review and protected-file items will appear here when operator attention is required."
              />
            }
            columns={[
              {
                key: "file",
                header: "File",
                render: (item) => (
                  <Link className="table-link" to={APP_ROUTES.reviewDetail(item.id)}>
                    <strong>{item.tracked_file.source_filename}</strong>
                    <span>{item.tracked_file.source_directory}</span>
                  </Link>
                ),
              },
              {
                key: "status",
                header: "Review",
                render: (item) => <StatusBadge value={item.review_status} />,
              },
              {
                key: "protected",
                header: "Protected",
                render: (item) =>
                  item.protected_state.is_protected ? (
                      <span className="badge-row">
                        <StatusBadge value="manual_review" />
                        <span>{formatProtectedSource(item.protected_state.source)}</span>
                      </span>
                  ) : (
                    "No"
                  ),
              },
              {
                key: "confidence",
                header: "Confidence",
                render: (item) => <StatusBadge value={item.confidence ?? "unknown"} />,
              },
              {
                key: "updated",
                header: "Latest activity",
                render: (item) => formatDateTime(item.latest_job_at ?? item.latest_plan_at ?? item.latest_probe_at),
              },
            ]}
          />
        </SectionCard>

        <SectionCard
          title="Review detail"
          subtitle={detail ? detail.tracked_file.source_filename : "Select a review item to inspect its plan, warnings, and protected state."}
        >
          {itemId && detailQuery.isLoading ? (
            <LoadingBlock label="Loading review detail" />
          ) : detail ? (
            <div className="card-stack">
              <KeyValueList
                items={[
                  { label: "Source path", value: detail.source_path },
                  { label: "Review status", value: <StatusBadge value={detail.review_status} /> },
                  { label: "Requires review", value: formatRelativeBoolean(detail.requires_review) },
                  { label: "Confidence", value: <StatusBadge value={detail.confidence ?? "unknown"} /> },
                  { label: "Protected", value: formatRelativeBoolean(detail.protected_state.is_protected) },
                  { label: "Protected source", value: formatProtectedSource(detail.protected_state.source) },
                  { label: "Latest decision", value: detail.latest_decision ? `${detail.latest_decision.decision_type} by ${detail.latest_decision.created_by_username}` : "No decision recorded" },
                ]}
              />

              <SectionCard title="Reasons" subtitle="Planner and job signals that caused review or cautious handling.">
                {detail.reasons.length === 0 && detail.warnings.length === 0 ? (
                  <EmptyState title="No review reasons" message="This item currently has no explicit reasons or warnings attached." />
                ) : (
                  <div className="card-stack">
                    {detail.reasons.length > 0 ? (
                      <div>
                        <h3 className="subsection-title">Reasons</h3>
                        <ul className="plain-list">
                          {detail.reasons.map((reason) => (
                            <li key={`reason-${reason.code}`}>
                              <strong>{reason.code}</strong>: {reason.message}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {detail.warnings.length > 0 ? (
                      <div>
                        <h3 className="subsection-title">Warnings</h3>
                        <ul className="plain-list">
                          {detail.warnings.map((warning) => (
                            <li key={`warning-${warning.code}`}>
                              <strong>{warning.code}</strong>: {warning.message}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                )}
              </SectionCard>

              <SectionCard title="Protected state" subtitle="Planner-derived and operator-applied protection are shown separately.">
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
              </SectionCard>

              {detail.latest_plan ? (
                <SectionCard title="Latest plan" subtitle={`Action: ${detail.latest_plan.action}`}>
                  <KeyValueList
                    items={[
                      { label: "Action", value: <StatusBadge value={detail.latest_plan.action} /> },
                      { label: "Confidence", value: <StatusBadge value={detail.latest_plan.confidence} /> },
                      { label: "Policy version", value: detail.latest_plan.policy_version },
                      { label: "Profile", value: detail.latest_plan.profile_name ?? "Default policy" },
                    ]}
                  />
                </SectionCard>
              ) : null}

              {detail.latest_job ? (
                <SectionCard title="Latest job" subtitle={`Job ${detail.latest_job.id.slice(0, 8)}`}>
                  <KeyValueList
                    items={[
                      { label: "Status", value: <StatusBadge value={detail.latest_job.status} /> },
                      { label: "Verification", value: <StatusBadge value={detail.latest_job.verification_status} /> },
                      { label: "Replacement", value: <StatusBadge value={detail.latest_job.replacement_status} /> },
                      { label: "Failure", value: detail.latest_job.failure_message ?? "None" },
                    ]}
                  />
                </SectionCard>
              ) : null}

              <SectionCard title="Operator actions" subtitle="All review decisions are explicit, authenticated, and auditable.">
                <div className="card-stack">
                  <label className="field">
                    <span>Decision note</span>
                    <textarea
                      value={decisionNote}
                      onChange={(event) => setDecisionNote(event.target.value)}
                      placeholder="Optional operator note for the review decision"
                      rows={4}
                    />
                  </label>
                  <div className="button-row">
                    <button
                      className="button button-primary"
                      type="button"
                      onClick={() => handleDecision("approve")}
                      disabled={isActionPending || !detail.requires_review}
                    >
                      {approveMutation.isPending ? "Approving…" : "Approve"}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => handleDecision("hold")}
                      disabled={isActionPending}
                    >
                      {holdMutation.isPending ? "Holding…" : "Hold"}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => handleDecision("reject")}
                      disabled={isActionPending}
                    >
                      {rejectMutation.isPending ? "Rejecting…" : "Reject"}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => handleDecision("mark_protected")}
                      disabled={isActionPending || detail.protected_state.operator_protected}
                    >
                      {protectMutation.isPending ? "Marking…" : "Mark protected"}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => handleDecision("clear_protected")}
                      disabled={isActionPending || !detail.protected_state.operator_protected}
                    >
                      {clearProtectedMutation.isPending ? "Clearing…" : "Clear protected"}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => handleDecision("replan")}
                      disabled={isActionPending}
                    >
                      {replanMutation.isPending ? "Replanning…" : "Replan"}
                    </button>
                    <button
                      className="button button-primary"
                      type="button"
                      onClick={() => handleDecision("create_job")}
                      disabled={isActionPending || detail.review_status !== "approved"}
                    >
                      {createJobMutation.isPending ? "Creating…" : "Create job"}
                    </button>
                  </div>
                </div>
              </SectionCard>

              {detail.latest_job ? (
                <SectionCard title="Latest job payloads" subtitle="Structured outputs remain secondary to the operator workflow.">
                  <PayloadViewer
                    payload={{
                      latest_job_id: detail.latest_job.id,
                      latest_plan_snapshot_id: detail.latest_plan_snapshot_id,
                      latest_probe_snapshot_id: detail.latest_probe_snapshot_id,
                    }}
                  />
                </SectionCard>
              ) : null}
            </div>
          ) : (
            <EmptyState
              title="No review item selected"
              message="Choose a manual-review item from the list to inspect the current plan, job state, and operator actions."
            />
          )}
        </SectionCard>
      </section>
    </div>
  );
}

function formatProtectedSource(value: string) {
  return value.split("_").join(" ");
}
