import { useId, useState, type PropsWithChildren } from "react";

export function CollapsibleSection({
  title,
  subtitle,
  defaultOpen = false,
  children,
}: PropsWithChildren<{
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
}>) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();

  return (
    <section className={`collapsible-section${open ? " collapsible-section-open" : ""}`}>
      <button
        className="collapsible-trigger"
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="collapsible-copy">
          <strong>{title}</strong>
          {subtitle ? <span>{subtitle}</span> : null}
        </span>
        <span className="collapsible-state">{open ? "Hide" : "Show"}</span>
      </button>
      {open ? (
        <div className="collapsible-body" id={panelId}>
          {children}
        </div>
      ) : null}
    </section>
  );
}
