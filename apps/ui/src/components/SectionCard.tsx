import type { PropsWithChildren, ReactNode } from "react";

export function SectionCard({
  title,
  subtitle,
  actions,
  className,
  children,
}: PropsWithChildren<{
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
}>) {
  return (
    <section className={`section-card${className ? ` ${className}` : ""}`}>
      <div className="section-card-header">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {actions ? <div className="section-card-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
