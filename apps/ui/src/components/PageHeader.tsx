import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  void eyebrow;
  void description;
  void actions;
  return <h1 className="sr-only">{title}</h1>;
}
