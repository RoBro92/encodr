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
  CreateJobPayload,
  CurrentUser,
  EffectiveConfig,
  FileDetail,
  FileListResponse,
  JobDetail,
  JobListResponse,
  LoginPayload,
  PlanFileResponse,
  PlanSnapshotDetail,
  ProbeFileResponse,
  ProbeOrPlanPayload,
  ProbeSnapshotDetail,
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
