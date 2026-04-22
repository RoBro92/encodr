import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveReviewItem,
  batchPlan,
  browseFolder,
  bootstrapAdmin,
  checkUpdateStatus,
  clearReviewItemProtected,
  createWatchedJob,
  createRemoteWorkerOnboarding,
  createBatchJobs,
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
  getExecutionPreferences,
  getBootstrapStatus,
  getEffectiveConfig,
  getFile,
  getScan,
  getLibraryRoots,
  getProcessingRules,
  getJob,
  getLatestPlanSnapshot,
  getLatestProbeSnapshot,
  getReviewItem,
  getRuntimeStatus,
  getStorageStatus,
  getUpdateStatus,
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
  dryRunSelection,
  rejectReviewItem,
  retryJob,
  runWorkerOnce,
  scanFolder,
  setupLocalWorker,
  enableWorker,
  listScans,
  listWatchedJobs,
  updateLibraryRoots,
  updateWatchedJob,
  updateWorkerPreferences,
  updateExecutionPreferences,
  updateProcessingRules,
} from "./endpoints";
import { useSession } from "../../features/auth/AuthProvider";
import type {
  CreateBatchJobsPayload,
  CreateJobPayload,
  FileSelectionPayload,
  LoginPayload,
  ProbeOrPlanPayload,
  ProcessingRuleValues,
  ReviewDecisionPayload,
  RemoteWorkerOnboardingPayload,
  WatchedJobPayload,
  WorkerPreferencePayload,
} from "../types/api";

export function useBootstrapStatusQuery(enabled = true) {
  const { apiClient } = useSession();
  return useQuery({
    queryKey: ["auth", "bootstrap-status"],
    queryFn: () => getBootstrapStatus(apiClient),
    enabled,
    retry: false,
  });
}

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

export function useBrowseFolderQuery(path?: string) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["library", "browse", path ?? "__root__"],
    queryFn: () => browseFolder(apiClient, path),
    enabled: isAuthenticated,
  });
}

export function useLibraryRootsQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["config", "library-roots"],
    queryFn: () => getLibraryRoots(apiClient),
    enabled: isAuthenticated,
  });
}

export function useScansQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["library", "scans"],
    queryFn: () => listScans(apiClient),
    enabled: isAuthenticated,
  });
}

export function useScanDetailQuery(scanId?: string) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["library", "scan", scanId],
    queryFn: () => getScan(apiClient, scanId as string),
    enabled: isAuthenticated && Boolean(scanId),
  });
}

export function useWatchedJobsQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["library", "watchers"],
    queryFn: () => listWatchedJobs(apiClient),
    enabled: isAuthenticated,
  });
}

export function useExecutionPreferencesQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["config", "execution-preferences"],
    queryFn: () => getExecutionPreferences(apiClient),
    enabled: isAuthenticated,
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

export function useSetupLocalWorkerMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: WorkerPreferencePayload) => setupLocalWorker(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workers"] }),
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
        queryClient.invalidateQueries({ queryKey: ["system"] }),
        queryClient.invalidateQueries({ queryKey: ["config", "execution-preferences"] }),
      ]);
    },
  });
}

export function useUpdateWorkerPreferencesMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ workerId, payload }: { workerId: string; payload: WorkerPreferencePayload }) =>
      updateWorkerPreferences(apiClient, workerId, payload),
    onSuccess: async (_, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workers"] }),
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
        queryClient.invalidateQueries({ queryKey: ["workers", "detail", variables.workerId] }),
        queryClient.invalidateQueries({ queryKey: ["system"] }),
        queryClient.invalidateQueries({ queryKey: ["config", "execution-preferences"] }),
      ]);
    },
  });
}

export function useCreateRemoteWorkerOnboardingMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RemoteWorkerOnboardingPayload) => createRemoteWorkerOnboarding(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workers"] }),
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
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

export function useUpdateStatusQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["system", "update"],
    queryFn: () => getUpdateStatus(apiClient),
    enabled: isAuthenticated,
  });
}

export function useUpdateExecutionPreferencesMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateExecutionPreferences.bind(null, apiClient),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["config", "execution-preferences"] }),
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
        queryClient.invalidateQueries({ queryKey: ["workers"] }),
        queryClient.invalidateQueries({ queryKey: ["system"] }),
      ]);
    },
  });
}

export function useCheckUpdateStatusMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => checkUpdateStatus(apiClient),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["system", "update"] });
    },
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

export function useUpdateLibraryRootsMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { movies_root?: string | null; tv_root?: string | null }) => updateLibraryRoots(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["config"] }),
        queryClient.invalidateQueries({ queryKey: ["system"] }),
      ]);
    },
  });
}

export function useProcessingRulesQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["config", "processing-rules"],
    queryFn: () => getProcessingRules(apiClient),
    enabled: isAuthenticated,
  });
}

export function useUpdateProcessingRulesMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      movies?: ProcessingRuleValues | null;
      movies_4k?: ProcessingRuleValues | null;
      tv?: ProcessingRuleValues | null;
      tv_4k?: ProcessingRuleValues | null;
    }) =>
      updateProcessingRules(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["config"] }),
        queryClient.invalidateQueries({ queryKey: ["files"] }),
        queryClient.invalidateQueries({ queryKey: ["review"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ]);
    },
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

export function useScanFolderMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProbeOrPlanPayload) => scanFolder(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["library", "scans"] }),
        queryClient.invalidateQueries({ queryKey: ["library", "watchers"] }),
      ]);
    },
  });
}

export function useCreateWatchedJobMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: WatchedJobPayload) => createWatchedJob(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["library", "watchers"] }),
        queryClient.invalidateQueries({ queryKey: ["library", "scans"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ]);
    },
  });
}

export function useUpdateWatchedJobMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ watchedJobId, payload }: { watchedJobId: string; payload: WatchedJobPayload }) =>
      updateWatchedJob(apiClient, watchedJobId, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["library", "watchers"] }),
        queryClient.invalidateQueries({ queryKey: ["library", "scans"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ]);
    },
  });
}

export function useDryRunMutation() {
  const { apiClient } = useSession();
  return useMutation({
    mutationFn: (payload: FileSelectionPayload) => dryRunSelection(apiClient, payload),
  });
}

export function useBatchPlanMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: FileSelectionPayload) => batchPlan(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["files"] }),
        queryClient.invalidateQueries({ queryKey: ["review"] }),
      ]);
    },
  });
}

export function useCreateBatchJobsMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateBatchJobsPayload) => createBatchJobs(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["files"] }),
        queryClient.invalidateQueries({ queryKey: ["review"] }),
      ]);
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

export function useBootstrapAdminMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LoginPayload) => bootstrapAdmin(apiClient, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "bootstrap-status"] });
    },
  });
}

export function useLogoutMutation() {
  const { apiClient } = useSession();
  return useMutation({
    mutationFn: () => logout(apiClient),
  });
}
