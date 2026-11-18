import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FilesPage } from "./FilesPage";

// Mock API hooks
vi.mock("../../lib/api/hooks", () => ({
  useFilesQuery: () => ({ data: { items: [], total: 0 }, isLoading: false }),
  useCreateJobMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useLibraryRootsQuery: () => ({ data: {}, isLoading: false }),
  useScansQuery: () => ({ data: { items: [] }, isLoading: false }),
  useWatchedJobsQuery: () => ({ data: { items: [] }, isLoading: false }),
  useWorkersQuery: () => ({ data: { items: [] }, isLoading: false }),
  useJobsQuery: () => ({ data: { items: [] }, isLoading: false }),
  useScanFolderMutation: () => ({ mutateAsync: vi.fn() }),
  useBrowseFolderQuery: () => ({ data: {}, isLoading: false }),
  useCreateDryRunJobsMutation: () => ({ mutateAsync: vi.fn() }),
  useCreateWatchedJobMutation: () => ({ mutateAsync: vi.fn() }),
  useUpdateLibraryRootsMutation: () => ({ mutateAsync: vi.fn() }),
  useUpdateWatchedJobMutation: () => ({ mutateAsync: vi.fn() }),
}));

// Mock Auth Provider
vi.mock("../auth/AuthProvider", () => ({
  useSession: () => ({ user: null }),
}));

// Mock BulkQueueProgress
vi.mock("../bulk-queue/BulkQueueProgress", () => ({
  useBulkQueueProgress: () => ({
    operation: null,
    active: false,
    terminal: true,
    start: vi.fn(),
  }),
  bulkProgressSummary: () => "Summary",
}));

const queryClient = new QueryClient();

describe("FilesPage", () => {
  it("renders without crashing", () => {
    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <FilesPage />
        </BrowserRouter>
      </QueryClientProvider>
    );
    expect(getByText("Library")).toBeInTheDocument();
  });
});
