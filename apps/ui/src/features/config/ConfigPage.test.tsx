import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigPage } from "./ConfigPage";

// Mock API hooks
vi.mock("../../lib/api/hooks", () => ({
  useGlobalConfigQuery: () => ({ data: {}, isLoading: false }),
  useUpdateGlobalConfigMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useLibraryRootsQuery: () => ({ data: {}, isLoading: false }),
  useProcessingRulesQuery: () => ({ data: null, isLoading: false }),
  useRuntimeStatusQuery: () => ({ data: { scratch_state: ["good"] }, isLoading: false }),
  useStorageStatusQuery: () => ({ data: { warnings: [], media_mounts: [], scratch: { status: "good" } }, isLoading: false }),
  useUpdateStatusQuery: () => ({ data: {}, isLoading: false }),
  useDiagnosticLogsQuery: () => ({ data: {}, isLoading: false }),
  useSystemInfoQuery: () => ({ data: {}, isLoading: false }),
  useCheckUpdateStatusMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateLibraryRootsMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateProcessingRulesMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useSystemOperationMutation: () => ({ mutate: vi.fn(), isPending: false }),
}));

// Mock Auth Provider
vi.mock("../auth/AuthProvider", () => ({
  useSession: () => ({ user: null }),
}));

const queryClient = new QueryClient();

describe("ConfigPage", () => {
  it("renders ok", () => {
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ConfigPage />
        </BrowserRouter>
      </QueryClientProvider>
    );
    expect(container).toBeTruthy();
  });
});
