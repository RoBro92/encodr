import { titleCase } from "../lib/utils/format";

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const status = value ?? "unknown";
  const tone = getTone(status);
  return <span className={`status-badge status-${tone}`}>{titleCase(status)}</span>;
}

function getTone(value: string) {
  if (["completed", "compliant", "passed", "succeeded", "ok", "running"].includes(value)) {
    return "positive";
  }
  if (["failed", "non_compliant", "manual_review"].includes(value)) {
    return "danger";
  }
  if (["pending", "queued", "planned", "warning", "skipped"].includes(value)) {
    return "warning";
  }
  return "neutral";
}
