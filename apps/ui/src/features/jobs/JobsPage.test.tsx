import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { JobsPage } from "./JobsPage";

// Mock API hooks
vi.mock("../../lib/api/hooks", () => ({
  useJobProgressStream: vi.fn(),
  useCancelJobMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useClearQueueMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateJobMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteJobBackupMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useFilesQuery: () => ({ data: { items: [], total: 0 }, isLoading: false }),
  useJobBackupsQuery: () => ({ data: { items: [], total: 0 }, isLoading: false }),
  useJobDetailQuery: () => ({ data: null, isLoading: false }),
  useJobsQuery: () => ({ data: { items: [], total: 0 }, isLoading: false }),
  useRetryJobMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useResolveFailedJobsMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useRestoreJobBackupMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useStripOnlyRecoveryMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useWorkerStatusQuery: () => ({ data: null, isLoading: false }),
}));

// Mock Auth Provider
vi.mock("../auth/AuthProvider", () => ({
  useSession: () => ({ user: null }),
}));

const queryClient = new QueryClient();

describe("JobsPage", () => {
  it("renders without crashing", () => {
    const { getByText, queryByText } = render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <JobsPage />
        </BrowserRouter>
      </QueryClientProvider>
    );
    expect(getByText("Jobs")).toBeInTheDocument();
    expect(getByText("Queue controls")).toBeInTheDocument();
  });
});
