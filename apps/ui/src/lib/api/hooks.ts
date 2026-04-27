import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import {
  approveReviewItem,
  batchPlan,
  browseFolder,
  bootstrapAdmin,
  cancelJob,
  checkUpdateStatus,
  clearReviewItemProtected,
  clearFailedJobs,
  clearQueue,
  createWatchedJob,
  createDryRunJobs,
  createRemoteWorkerOnboarding,
  createBatchJobs,
  createJobFromReviewItem,
  excludeReviewItem,
  disableWorker,
  deleteWorker,
  deleteJobBackup,
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
  getDiagnosticLogs,
  getWorker,
  getWorkerStatus,
  holdReviewItem,
  listWorkers,
  listJobBackups,
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
  restoreJobBackup,
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
  CreateDryRunJobsPayload,
  FileSelectionPayload,
  JobDetail,
  JobBackupListResponse,
  JobListResponse,
  JobSummary,
  LoginPayload,
  ProbeOrPlanPayload,
  ProcessingRuleValues,
  ReviewDecisionPayload,
  RemoteWorkerOnboardingPayload,
  WatchedJobPayload,
  WorkerPreferencePayload,
} from "../types/api";

const TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "interrupted", "cancelled", "manual_review", "skipped"]);
const UPDATE_STATUS_STALE_MS = 60 * 1000;
const UPDATE_STATUS_REFETCH_MS = 5 * 60 * 1000;

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

export function useJobProgressStream() {
  const { apiClient, isAuthenticated } = useSession();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!isAuthenticated) {
      return undefined;
    }

    const controller = new AbortController();
    void (async () => {
      try {
        const response = await apiClient.stream("/jobs/progress-stream", {
          headers: { Accept: "text/event-stream" },
          signal: controller.signal,
        });
        await readJobProgressStream(response, (items) => {
          applyJobProgressUpdates(queryClient, items);
        });
      } catch (error) {
        if (!controller.signal.aborted) {
          console.warn("Job progress stream disconnected.", error);
        }
      }
    })();

    return () => {
      controller.abort();
    };
  }, [apiClient, isAuthenticated, queryClient]);
}

async function readJobProgressStream(
  response: Response,
  onJobs: (items: JobSummary[]) => void,
) {
  const reader = response.body?.getReader();
  if (!reader) {
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    while (true) {
      const delimiter = buffer.match(/\r?\n\r?\n/);
      if (!delimiter || delimiter.index == null) {
        break;
      }
      const block = buffer.slice(0, delimiter.index);
      buffer = buffer.slice(delimiter.index + delimiter[0].length);
      parseJobProgressEvent(block, onJobs);
    }
  }
}

function parseJobProgressEvent(
  block: string,
  onJobs: (items: JobSummary[]) => void,
) {
  let eventName = "message";
  const dataLines: string[] = [];

  for (const rawLine of block.replace(/\r\n/g, "\n").split("\n")) {
    if (rawLine.startsWith("event:")) {
      eventName = rawLine.slice("event:".length).trim();
    } else if (rawLine.startsWith("data:")) {
      dataLines.push(rawLine.slice("data:".length).trimStart());
    }
  }

  if (eventName !== "jobs" || dataLines.length === 0) {
    return;
  }

  try {
    const payload = JSON.parse(dataLines.join("\n")) as { items?: JobSummary[] };
    if (Array.isArray(payload.items)) {
      onJobs(payload.items);
    }
  } catch {
    return;
  }
}

function applyJobProgressUpdates(queryClient: QueryClient, items: JobSummary[]) {
  if (items.length === 0) {
    return;
  }

  const updates = new Map(items.map((item) => [item.id, item]));
  for (const query of queryClient.getQueryCache().findAll({ queryKey: ["jobs"] })) {
    const queryKey = query.queryKey;
    if (queryKey[1] === "detail") {
      continue;
    }
    const filters = isJobFilterQueryKey(queryKey[1]) ? queryKey[1] : {};
    queryClient.setQueryData<JobListResponse>(queryKey, (current) => {
      if (!current?.items) {
        return current;
      }
      let changed = false;
      const seen = new Set<string>();
      const nextItems = current.items.flatMap((item) => {
        const update = updates.get(item.id);
        if (!update) {
          return [item];
        }
        seen.add(item.id);
        const merged = { ...item, ...update };
        changed = true;
        return matchesJobFilters(merged, filters) ? [merged] : [];
      });
      for (const update of items) {
        if (!seen.has(update.id) && matchesJobFilters(update, filters)) {
          nextItems.unshift(update);
          changed = true;
        }
      }
      return changed ? { ...current, items: nextItems } : current;
    });
  }

  for (const update of items) {
    queryClient.setQueryData<JobDetail>(["jobs", "detail", update.id], (current) =>
      current ? { ...current, ...update } : current,
    );
  }

  if (items.some((item) => TERMINAL_JOB_STATUSES.has(item.status))) {
    void queryClient.invalidateQueries({ queryKey: ["jobs"], refetchType: "active" });
    void queryClient.invalidateQueries({ queryKey: ["worker", "status"], refetchType: "active" });
    void queryClient.invalidateQueries({ queryKey: ["analytics", "dashboard"], refetchType: "active" });
  }
}

function isJobFilterQueryKey(value: unknown): value is Record<string, string | number | undefined> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function matchesJobFilters(job: JobSummary, filters: Record<string, string | number | undefined>) {
  if (filters.status && job.status !== filters.status) {
    return false;
  }
  if (filters.file_id && job.tracked_file_id !== filters.file_id) {
    return false;
  }
  if (filters.job_kind && job.job_kind !== filters.job_kind) {
    return false;
  }
  if (filters.worker_name && job.worker_name !== filters.worker_name) {
    return false;
  }
  return true;
}

export function useCancelJobMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelJob(apiClient, jobId),
    onSuccess: async (job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs", "detail", job.id] }),
        queryClient.invalidateQueries({ queryKey: ["worker", "status"] }),
        queryClient.invalidateQueries({ queryKey: ["workers", "inventory"] }),
        queryClient.invalidateQueries({ queryKey: ["workers"] }),
      ]);
    },
  });
}

export function useClearQueueMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => clearQueue(apiClient),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["worker"] }),
        queryClient.invalidateQueries({ queryKey: ["analytics"] }),
      ]);
    },
  });
}

export function useClearFailedJobsMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => clearFailedJobs(apiClient),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["analytics"] }),
      ]);
    },
  });
}

export function useJobBackupsQuery(filters: Record<string, string | number | undefined> = {}) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery<JobBackupListResponse>({
    queryKey: ["jobs", "backups", filters],
    queryFn: () => listJobBackups(apiClient, filters),
    enabled: isAuthenticated,
  });
}

export function useDeleteJobBackupMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => deleteJobBackup(apiClient, jobId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs", "backups"] }),
      ]);
    },
  });
}

export function useRestoreJobBackupMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => restoreJobBackup(apiClient, jobId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs", "backups"] }),
        queryClient.invalidateQueries({ queryKey: ["files"] }),
        queryClient.invalidateQueries({ queryKey: ["review"] }),
      ]);
    },
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

export function useDeleteWorkerMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (workerId: string) => deleteWorker(apiClient, workerId),
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

export function useDiagnosticLogsQuery(filters: Record<string, string | number | undefined>) {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["system", "logs", filters],
    queryFn: () => getDiagnosticLogs(apiClient, filters),
    enabled: isAuthenticated,
  });
}

export function useUpdateStatusQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["system", "update"],
    queryFn: () => getUpdateStatus(apiClient),
    enabled: isAuthenticated,
    staleTime: UPDATE_STATUS_STALE_MS,
    refetchInterval: isAuthenticated ? UPDATE_STATUS_REFETCH_MS : false,
    refetchIntervalInBackground: false,
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
    onSuccess: (result) => {
      queryClient.setQueryData(["system", "update"], result);
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
        queryClient.invalidateQueries({ queryKey: ["files"] }),
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

export function useCreateDryRunJobsMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateDryRunJobsPayload) => createDryRunJobs(apiClient, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["files"] }),
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

export function useExcludeReviewItemMutation() {
  const { apiClient } = useSession();
  return useReviewDecisionMutation(({ itemId, request }) => excludeReviewItem(apiClient, itemId, request));
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
