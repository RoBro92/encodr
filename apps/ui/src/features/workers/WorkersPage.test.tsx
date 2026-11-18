import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WorkersPage } from "./WorkersPage";

// Mock API hooks
vi.mock("../../lib/api/hooks", () => ({
  useWorkersQuery: () => ({ data: { items: [], total: 0 }, isLoading: false }),
  useWorkerStatusQuery: () => ({ data: { status: "", hardware_probes: [] }, isLoading: false }),
  useWorkerDetailQuery: () => ({ data: { status: "", worker_type: "", host_summary: { hostname: "" }, capability_summary: { execution_modes: [] }, assigned_job_ids: [] }, isLoading: false }),
  useUpdateWorkerMutation: () => ({ mutateAsync: vi.fn() }),
  useEnableWorkerMutation: () => ({ mutateAsync: vi.fn() }),
  useDisableWorkerMutation: () => ({ mutateAsync: vi.fn() }),
  useSetupLocalWorkerMutation: () => ({ mutateAsync: vi.fn() }),
  useRemoveWorkerMutation: () => ({ mutateAsync: vi.fn() }),
  useUpdateWorkerPreferencesMutation: () => ({ mutateAsync: vi.fn() }),
  useCreateRemoteWorkerOnboardingMutation: () => ({ mutateAsync: vi.fn() }),
  useDeleteWorkerMutation: () => ({ mutateAsync: vi.fn() }),
}));

// Mock Auth Provider
vi.mock("../auth/AuthProvider", () => ({
  useSession: () => ({ user: null }),
}));

const queryClient = new QueryClient();

describe("WorkersPage", () => {
  it("renders ok", () => {
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <WorkersPage />
        </BrowserRouter>
      </QueryClientProvider>
    );
    expect(container).toBeTruthy();
  });
});
