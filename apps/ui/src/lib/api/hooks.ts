import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createJob,
  getCurrentUser,
  getEffectiveConfig,
  getFile,
  getJob,
  getLatestPlanSnapshot,
  getLatestProbeSnapshot,
  getRuntimeStatus,
  getStorageStatus,
  getWorkerStatus,
  listFiles,
  listJobs,
  login,
  logout,
  planFile,
  probeFile,
  retryJob,
  runWorkerOnce,
} from "./endpoints";
import { useSession } from "../../features/auth/AuthProvider";
import type { CreateJobPayload, LoginPayload, ProbeOrPlanPayload } from "../types/api";

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

export function useWorkerStatusQuery() {
  const { apiClient, isAuthenticated } = useSession();
  return useQuery({
    queryKey: ["worker", "status"],
    queryFn: () => getWorkerStatus(apiClient),
    enabled: isAuthenticated,
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

export function useProbeFileMutation() {
  const { apiClient } = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProbeOrPlanPayload) => probeFile(apiClient, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["files"] });
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
      ]);
    },
  });
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
