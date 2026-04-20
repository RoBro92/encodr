import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveReviewItem,
  clearReviewItemProtected,
  createJobFromReviewItem,
  disableWorker,
  getAnalyticsDashboard,
  getAnalyticsMedia,
  getAnalyticsOutcomes,
  getAnalyticsOverview,
  getAnalyticsRecent,
  getAnalyticsStorage,
  createJob,
  getCurrentUser,
  getEffectiveConfig,
  getFile,
  getJob,
  getLatestPlanSnapshot,
  getLatestProbeSnapshot,
  getReviewItem,
  getRuntimeStatus,
  getStorageStatus,
  getWorker,
  getWorkerStatus,
  holdReviewItem,
  listWorkers,
  listReviewItems,
  markReviewItemProtected,
  runWorkerSelfTest,
  replanReviewItem,
  listFiles,
  listJobs,
  login,
  logout,
  planFile,
  probeFile,
  rejectReviewItem,
  retryJob,
  runWorkerOnce,
  enableWorker,
} from "./endpoints";
import { useSession } from "../../features/auth/AuthProvider";
import type { CreateJobPayload, LoginPayload, ProbeOrPlanPayload, ReviewDecisionPayload } from "../types/api";

export function useCurrentUserQuery(enabled = true) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => getCurrentUser(apiClient),
    enabled: enabled && isAuthenticated,
  });
}

export function useFilesQuery(filters: Record<string, string | number | boolean | undefined>) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["files", filters],
    queryFn: () => listFiles(apiClient, filters),
    enabled: isAuthenticated,
  });
}

export function useFileDetailQuery(fileId?: string) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["files", "detail", fileId],
    queryFn: () => getFile(apiClient, fileId as string),
    enabled: isAuthenticated && Boolean(fileId),
  });
}

export function useLatestProbeQuery(fileId?: string) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["files", "probe", fileId],
    queryFn: () => getLatestProbeSnapshot(apiClient, fileId as string),
    enabled: isAuthenticated && Boolean(fileId),
  });
}

export function useLatestPlanQuery(fileId?: string) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["files", "plan", fileId],
    queryFn: () => getLatestPlanSnapshot(apiClient, fileId as string),
    enabled: isAuthenticated && Boolean(fileId),
  });
}

export function useJobsQuery(filters: Record<string, string | number | undefined>) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["jobs", filters],
    queryFn: () => listJobs(apiClient, filters),
    enabled: isAuthenticated,
  });
}

export function useJobDetailQuery(jobId?: string) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["jobs", "detail", jobId],
    queryFn: () => getJob(apiClient, jobId as string),
    enabled: isAuthenticated && Boolean(jobId),
  });
}

export function useReviewItemsQuery(filters: Record<string, string | number | boolean | undefined>) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["review", "items", filters],
    queryFn: () => listReviewItems(apiClient, filters),
    enabled: isAuthenticated,
  });
}

export function useReviewItemDetailQuery(itemId?: string) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["review", "detail", itemId],
    queryFn: () => getReviewItem(apiClient, itemId as string),
    enabled: isAuthenticated && Boolean(itemId),
  });
}

export function useWorkerStatusQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["worker", "status"],
    queryFn: () => getWorkerStatus(apiClient),
    enabled: isAuthenticated,
  });
}

export function useWorkersQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["workers", "inventory"],
    queryFn: () => listWorkers(apiClient),
    enabled: isAuthenticated,
  });
}

export function useWorkerDetailQuery(workerId?: string) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["workers", "detail", workerId],
    queryFn: () => getWorker(apiClient, workerId as string),
    enabled: isAuthenticated && Boolean(workerId),
  });
}

export function useWorkerSelfTestMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => runWorkerSelfTest(apiClient),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
        queryClient.invalidateQueries({ queryKey: ["workers"] }),
        queryClient.invalidateQueries({ queryKey: ["system"] }),
      ]);
    },
  });
}

export function useEnableWorkerMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (workerId: string) => enableWorker(apiClient, workerId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workers"] }),
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
        queryClient.invalidateQueries({ queryKey: ["system"] }),
      ]);
    },
  });
}

export function useDisableWorkerMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (workerId: string) => disableWorker(apiClient, workerId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workers"] }),
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
        queryClient.invalidateQueries({ queryKey: ["system"] }),
      ]);
    },
  });
}

export function useStorageStatusQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["system", "storage"],
    queryFn: () => getStorageStatus(apiClient),
    enabled: isAuthenticated,
  });
}

export function useRuntimeStatusQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["system", "runtime"],
    queryFn: () => getRuntimeStatus(apiClient),
    enabled: isAuthenticated,
  });
}

export function useEffectiveConfigQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["config", "effective"],
    queryFn: () => getEffectiveConfig(apiClient),
    enabled: isAuthenticated,
  });
}

export function useAnalyticsOverviewQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: () => getAnalyticsOverview(apiClient),
    enabled: isAuthenticated,
  });
}

export function useAnalyticsStorageQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["analytics", "storage"],
    queryFn: () => getAnalyticsStorage(apiClient),
    enabled: isAuthenticated,
  });
}

export function useAnalyticsOutcomesQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["analytics", "outcomes"],
    queryFn: () => getAnalyticsOutcomes(apiClient),
    enabled: isAuthenticated,
  });
}

export function useAnalyticsMediaQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["analytics", "media"],
    queryFn: () => getAnalyticsMedia(apiClient),
    enabled: isAuthenticated,
  });
}

export function useAnalyticsRecentQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["analytics", "recent"],
    queryFn: () => getAnalyticsRecent(apiClient),
    enabled: isAuthenticated,
  });
}

export function useAnalyticsDashboardQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["analytics", "dashboard"],
    queryFn: () => getAnalyticsDashboard(apiClient),
    enabled: isAuthenticated,
  });
}

export function useProbeFileMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProbeOrPlanPayload) => probeFile(apiClient, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["files"] });
      await queryClient.invalidateQueries({ queryKey: ["review"] });
    },
  });
}

export function usePlanFileMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProbeOrPlanPayload) => planFile(apiClient, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["files"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["review"] });
    },
  });
}

export function useCreateJobMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateJobPayload) => createJob(apiClient, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["files"] });
      await queryClient.invalidateQueries({ queryKey: ["review"] });
    },
  });
}

export function useRetryJobMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => retryJob(apiClient, jobId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["review"] });
    },
  });
}

export function useRunWorkerOnceMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => runWorkerOnce(apiClient),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["files"] }),
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
        queryClient.invalidateQueries({ queryKey: ["system"] }),
        queryClient.invalidateQueries({ queryKey: ["analytics"] }),
        queryClient.invalidateQueries({ queryKey: ["review"] }),
      ]);
    },
  });
}

function useReviewDecisionMutation(
  mutationFn: (payload: { itemId: string; request: ReviewDecisionPayload }) => Promise<unknown>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review"] }),
        queryClient.invalidateQueries({ queryKey: ["files"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["analytics"] }),
      ]);
    },
  });
}

export function useApproveReviewItemMutation() {
  const { apiClient } = useSession();
  return useReviewDecisionMutation(({ itemId, request }) => approveReviewItem(apiClient, itemId, request));
}

export function useRejectReviewItemMutation() {
  const { apiClient } = useSession();
  return useReviewDecisionMutation(({ itemId, request }) => rejectReviewItem(apiClient, itemId, request));
}

export function useHoldReviewItemMutation() {
  const { apiClient } = useSession();
  return useReviewDecisionMutation(({ itemId, request }) => holdReviewItem(apiClient, itemId, request));
}

export function useMarkReviewItemProtectedMutation() {
  const { apiClient } = useSession();
  return useReviewDecisionMutation(({ itemId, request }) => markReviewItemProtected(apiClient, itemId, request));
}

export function useClearReviewItemProtectedMutation() {
  const { apiClient } = useSession();
  return useReviewDecisionMutation(({ itemId, request }) => clearReviewItemProtected(apiClient, itemId, request));
}

export function useReplanReviewItemMutation() {
  const { apiClient } = useSession();
  return useReviewDecisionMutation(({ itemId, request }) => replanReviewItem(apiClient, itemId, request));
}

export function useCreateJobFromReviewItemMutation() {
  const { apiClient } = useSession();
  return useReviewDecisionMutation(({ itemId, request }) => createJobFromReviewItem(apiClient, itemId, request));
}

export function useLoginMutation() {
  const { apiClient } = useSession();
  return useMutation({
    mutationFn: (payload: LoginPayload) => login(apiClient, payload),
  });
}

export function useLogoutMutation() {
  const { apiClient } = useSession();
  return useMutation({
    mutationFn: () => logout(apiClient),
  });
}
