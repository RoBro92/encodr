export function ExplainedStatusBadge({
      label,
      value,
      tone,
      title,
    }: {
          label: string;
          value: string;
          tone: "neutral" | "info" | "success" | "warning" | "danger" | "active";
          title: string;
        }) {
    return (
    <span className={`explained-status-badge explained-status-badge-${tone}`} title={title}>
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
    );
}
