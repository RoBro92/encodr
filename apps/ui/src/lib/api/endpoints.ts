import type {
  ApiClient,
} from "./client";
import type {
  AnalyticsDashboard,
  AnalyticsMedia,
  AnalyticsOutcomes,
  AnalyticsOverview,
  AnalyticsStorage,
  AuthTokens,
  BootstrapStatus,
  BatchPlanResponse,
  BatchJobCreateResponse,
  CreateJobPayload,
  CreateBatchJobsPayload,
  CurrentUser,
  EffectiveConfig,
  FileDetail,
  FileListResponse,
  FileSelectionPayload,
  FolderBrowseResponse,
  FolderScanSummary,
  JobDetail,
  JobListResponse,
  LibraryRoots,
  LoginPayload,
  PlanFileResponse,
  PlanSnapshotDetail,
  ProcessingRules,
  ProcessingRuleValues,
  ProbeFileResponse,
  ProbeOrPlanPayload,
  ProbeSnapshotDetail,
  DryRunBatchResponse,
  RecentAnalytics,
  RuntimeStatus,
  StorageStatus,
  UpdateStatus,
  ReviewDecisionPayload,
  ReviewDecisionResponse,
  ReviewItemDetail,
  ReviewListResponse,
  WorkerInventoryDetail,
  WorkerInventoryListResponse,
  WorkerRunOnceResponse,
  WorkerStateChangeResponse,
  WorkerSelfTestResponse,
  WorkerStatus,
} from "../types/api";

export function login(client: ApiClient, payload: LoginPayload): Promise<AuthTokens> {
  return client.request<AuthTokens>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  }, { auth: false, retryOnUnauthorised: false });
}

export function getBootstrapStatus(client: ApiClient): Promise<BootstrapStatus> {
  return client.request<BootstrapStatus>("/auth/bootstrap-status", {}, { auth: false, retryOnUnauthorised: false });
}

export function bootstrapAdmin(client: ApiClient, payload: LoginPayload): Promise<{ user: CurrentUser }> {
  return client.request<{ user: CurrentUser }>(
    "/auth/bootstrap-admin",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { auth: false, retryOnUnauthorised: false },
  );
}

export function logout(client: ApiClient): Promise<{ status: string }> {
  return client.request<{ status: string }>("/auth/logout", { method: "POST" });
}

export function getCurrentUser(client: ApiClient): Promise<CurrentUser> {
  return client.request<CurrentUser>("/auth/me");
}

export function listFiles(
  client: ApiClient,
  query: Record<string, string | number | boolean | undefined>,
): Promise<FileListResponse> {
  const search = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  return client.request<FileListResponse>(`/files${suffix}`);
}

export function getFile(client: ApiClient, fileId: string): Promise<FileDetail> {
  return client.request<FileDetail>(`/files/${fileId}`);
}

export function getLatestProbeSnapshot(client: ApiClient, fileId: string): Promise<ProbeSnapshotDetail> {
  return client.request<ProbeSnapshotDetail>(`/files/${fileId}/probe-snapshots/latest`);
}

export function getLatestPlanSnapshot(client: ApiClient, fileId: string): Promise<PlanSnapshotDetail> {
  return client.request<PlanSnapshotDetail>(`/files/${fileId}/plan-snapshots/latest`);
}

export function probeFile(client: ApiClient, payload: ProbeOrPlanPayload): Promise<ProbeFileResponse> {
  return client.request<ProbeFileResponse>("/files/probe", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function planFile(client: ApiClient, payload: ProbeOrPlanPayload): Promise<PlanFileResponse> {
  return client.request<PlanFileResponse>("/files/plan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function browseFolder(client: ApiClient, path?: string): Promise<FolderBrowseResponse> {
  const suffix = path ? `?path=${encodeURIComponent(path)}` : "";
  return client.request<FolderBrowseResponse>(`/files/browse${suffix}`);
}

export function scanFolder(client: ApiClient, payload: ProbeOrPlanPayload): Promise<FolderScanSummary> {
  return client.request<FolderScanSummary>("/files/scan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function dryRunSelection(client: ApiClient, payload: FileSelectionPayload): Promise<DryRunBatchResponse> {
  return client.request<DryRunBatchResponse>("/files/dry-run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function batchPlan(client: ApiClient, payload: FileSelectionPayload): Promise<BatchPlanResponse> {
  return client.request<BatchPlanResponse>("/files/batch-plan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listJobs(
  client: ApiClient,
  query: Record<string, string | number | undefined>,
): Promise<JobListResponse> {
  const search = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  return client.request<JobListResponse>(`/jobs${suffix}`);
}

export function getJob(client: ApiClient, jobId: string): Promise<JobDetail> {
  return client.request<JobDetail>(`/jobs/${jobId}`);
}

export function listWorkers(client: ApiClient): Promise<WorkerInventoryListResponse> {
  return client.request<WorkerInventoryListResponse>("/workers");
}

export function getWorker(client: ApiClient, workerId: string): Promise<WorkerInventoryDetail> {
  return client.request<WorkerInventoryDetail>(`/workers/${workerId}`);
}

export function enableWorker(client: ApiClient, workerId: string): Promise<WorkerStateChangeResponse> {
  return client.request<WorkerStateChangeResponse>(`/workers/${workerId}/enable`, { method: "POST" });
}

export function disableWorker(client: ApiClient, workerId: string): Promise<WorkerStateChangeResponse> {
  return client.request<WorkerStateChangeResponse>(`/workers/${workerId}/disable`, { method: "POST" });
}

export function listReviewItems(
  client: ApiClient,
  query: Record<string, string | number | boolean | undefined>,
): Promise<ReviewListResponse> {
  const search = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  return client.request<ReviewListResponse>(`/review/items${suffix}`);
}

export function getReviewItem(client: ApiClient, itemId: string): Promise<ReviewItemDetail> {
  return client.request<ReviewItemDetail>(`/review/items/${itemId}`);
}

function postReviewDecision(
  client: ApiClient,
  itemId: string,
  action: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResponse> {
  return client.request<ReviewDecisionResponse>(`/review/items/${itemId}/${action}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function approveReviewItem(
  client: ApiClient,
  itemId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResponse> {
  return postReviewDecision(client, itemId, "approve", payload);
}

export function rejectReviewItem(
  client: ApiClient,
  itemId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResponse> {
  return postReviewDecision(client, itemId, "reject", payload);
}

export function holdReviewItem(
  client: ApiClient,
  itemId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResponse> {
  return postReviewDecision(client, itemId, "hold", payload);
}

export function markReviewItemProtected(
  client: ApiClient,
  itemId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResponse> {
  return postReviewDecision(client, itemId, "mark-protected", payload);
}

export function clearReviewItemProtected(
  client: ApiClient,
  itemId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResponse> {
  return postReviewDecision(client, itemId, "clear-protected", payload);
}

export function replanReviewItem(
  client: ApiClient,
  itemId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResponse> {
  return postReviewDecision(client, itemId, "replan", payload);
}

export function createJobFromReviewItem(
  client: ApiClient,
  itemId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResponse> {
  return postReviewDecision(client, itemId, "create-job", payload);
}

export function createJob(client: ApiClient, payload: CreateJobPayload): Promise<JobDetail> {
  return client.request<JobDetail>("/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createBatchJobs(client: ApiClient, payload: CreateBatchJobsPayload): Promise<BatchJobCreateResponse> {
  return client.request<BatchJobCreateResponse>("/jobs/batch", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function retryJob(client: ApiClient, jobId: string): Promise<JobDetail> {
  return client.request<JobDetail>(`/jobs/${jobId}/retry`, { method: "POST" });
}

export function runWorkerOnce(client: ApiClient): Promise<WorkerRunOnceResponse> {
  return client.request<WorkerRunOnceResponse>("/worker/run-once", { method: "POST" });
}

export function getWorkerStatus(client: ApiClient): Promise<WorkerStatus> {
  return client.request<WorkerStatus>("/worker/status");
}

export function runWorkerSelfTest(client: ApiClient): Promise<WorkerSelfTestResponse> {
  return client.request<WorkerSelfTestResponse>("/worker/self-test", { method: "POST" });
}

export function getStorageStatus(client: ApiClient): Promise<StorageStatus> {
  return client.request<StorageStatus>("/system/storage");
}

export function getRuntimeStatus(client: ApiClient): Promise<RuntimeStatus> {
  return client.request<RuntimeStatus>("/system/runtime");
}

export function getUpdateStatus(client: ApiClient): Promise<UpdateStatus> {
  return client.request<UpdateStatus>("/system/update");
}

export function checkUpdateStatus(client: ApiClient): Promise<UpdateStatus> {
  return client.request<UpdateStatus>("/system/update/check", { method: "POST" });
}

export function getEffectiveConfig(client: ApiClient): Promise<EffectiveConfig> {
  return client.request<EffectiveConfig>("/config/effective");
}

export function getLibraryRoots(client: ApiClient): Promise<LibraryRoots> {
  return client.request<LibraryRoots>("/config/setup/library-roots");
}

export function updateLibraryRoots(
  client: ApiClient,
  payload: { movies_root?: string | null; tv_root?: string | null },
): Promise<LibraryRoots> {
  return client.request<LibraryRoots>("/config/setup/library-roots", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getProcessingRules(client: ApiClient): Promise<ProcessingRules> {
  return client.request<ProcessingRules>("/config/setup/processing-rules");
}

export function updateProcessingRules(
  client: ApiClient,
  payload: {
    movies?: ProcessingRuleValues | null;
    movies_4k?: ProcessingRuleValues | null;
    tv?: ProcessingRuleValues | null;
    tv_4k?: ProcessingRuleValues | null;
  },
): Promise<ProcessingRules> {
  return client.request<ProcessingRules>("/config/setup/processing-rules", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getAnalyticsOverview(client: ApiClient): Promise<AnalyticsOverview> {
  return client.request<AnalyticsOverview>("/analytics/overview");
}

export function getAnalyticsStorage(client: ApiClient): Promise<AnalyticsStorage> {
  return client.request<AnalyticsStorage>("/analytics/storage");
}

export function getAnalyticsOutcomes(client: ApiClient): Promise<AnalyticsOutcomes> {
  return client.request<AnalyticsOutcomes>("/analytics/outcomes");
}

export function getAnalyticsMedia(client: ApiClient): Promise<AnalyticsMedia> {
  return client.request<AnalyticsMedia>("/analytics/media");
}

export function getAnalyticsRecent(client: ApiClient): Promise<RecentAnalytics> {
  return client.request<RecentAnalytics>("/analytics/recent");
}

export function getAnalyticsDashboard(client: ApiClient): Promise<AnalyticsDashboard> {
  return client.request<AnalyticsDashboard>("/analytics/dashboard");
}
