import { titleCase } from "../lib/utils/format";

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const status = value ?? "unknown";
  const tone = getTone(status);
  return (
    <span className={`status-badge status-${tone}`} data-status={status}>
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
