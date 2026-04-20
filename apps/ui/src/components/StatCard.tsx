import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  tone = "default",
  detail,
}: {
  label: string;
  value: string | number;
  tone?: "default" | "positive" | "warning" | "danger";
  detail?: ReactNode;
}) {
  return (
    <article className={`stat-card stat-card-${tone}`}>
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {detail ? <div className="stat-detail">{detail}</div> : null}
    </article>
  );
}
