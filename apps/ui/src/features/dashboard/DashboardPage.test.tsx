import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardWidgetBoundary } from "./DashboardPage";

function RenderProbe({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("Malformed live dashboard data");
  }
  return <div>Recovered widget</div>;
}

describe("DashboardWidgetBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("recovers when fresh dashboard data arrives after a transient render error", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const { rerender } = render(
      <DashboardWidgetBoundary title="Active file" resetKey="bad-update">
        <RenderProbe shouldThrow />
      </DashboardWidgetBoundary>,
    );

    expect(await screen.findByText(/active file unavailable/i)).toBeInTheDocument();

    rerender(
      <DashboardWidgetBoundary title="Active file" resetKey="fresh-update">
        <RenderProbe shouldThrow={false} />
      </DashboardWidgetBoundary>,
    );

    expect(await screen.findByText(/recovered widget/i)).toBeInTheDocument();
  });
});
