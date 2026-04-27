import { titleCase } from "../lib/utils/format";

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const status = value ?? "unknown";
  const tone = getTone(status);
  return (
    <span className={`status-badge status-${tone}`} data-status={status} title={statusExplanation(status)}>
      {titleCase(status)}
    </span>
  );
}

function getTone(value: string) {
  if (["completed", "compliant", "passed", "succeeded", "ok", "running", "healthy", "approved", "resolved", "custom"].includes(value)) {
    return "positive";
  }
  if (["failed", "non_compliant", "manual_review", "open", "rejected"].includes(value)) {
    return "danger";
  }
  if (["pending", "queued", "planned", "warning", "skipped", "degraded", "held", "protected", "not_configured", "disabled", "selected", "default"].includes(value)) {
    return "warning";
  }
  return "neutral";
}

function statusExplanation(value: string) {
  const normalized = value.toLowerCase();
  const labels: Record<string, string> = {
    pending: "Queued and waiting for a worker or scheduling condition.",
    queued: "Queued and waiting for a worker.",
    running: "Work is currently in progress.",
    completed: "Work completed successfully.",
    failed: "Work failed and needs operator attention.",
    interrupted: "Work stopped before completion.",
    cancelled: "Work was cancelled by an operator.",
    skipped: "No processing was performed because the active policy did not require it.",
    manual_review: "Manual review is required before work can continue.",
    open: "This review item still needs a decision.",
    approved: "This review item has been approved.",
    held: "This review item is held for later action.",
    rejected: "This review item has been rejected.",
    resolved: "This item is resolved from the operator perspective.",
    protected: "This file is protected by policy or operator decision.",
    healthy: "The component is healthy.",
    degraded: "The component is usable but needs attention.",
    failed_health: "The component is not usable.",
  };
  return labels[normalized] ?? `Status: ${titleCase(value)}`;
}
