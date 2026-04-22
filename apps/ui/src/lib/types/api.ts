export type AuthTokens = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  access_token_expires_in: number;
  refresh_token_expires_in: number;
};

export type BootstrapStatus = {
  bootstrap_allowed: boolean;
  first_user_setup_required: boolean;
  user_count: number;
  version: string;
};

export type CurrentUser = {
  id: string;
  username: string;
  role: string;
  is_active: boolean;
  is_bootstrap_admin: boolean;
  last_login_at: string | null;
};

export type FileSummary = {
  id: string;
  source_path: string;
  source_filename: string;
  source_extension: string | null;
  source_directory: string;
  last_observed_size: number | null;
  last_observed_modified_time: string | null;
  fingerprint_placeholder: string | null;
  is_4k: boolean;
  lifecycle_state: string;
  compliance_state: string;
  is_protected: boolean;
  operator_protected: boolean;
  protected_source: string | null;
  operator_protected_note: string | null;
  requires_review: boolean;
  review_status: string | null;
  last_processed_policy_version: number | null;
  last_processed_profile_name: string | null;
  created_at: string;
  updated_at: string;
};

export type FileDetail = FileSummary & {
  latest_probe_snapshot_id: string | null;
  latest_plan_snapshot_id: string | null;
};

export type ProbeSnapshotSummary = {
  id: string;
  tracked_file_id: string;
  schema_version: number;
  created_at: string;
  file_name: string | null;
  format_name: string | null;
  duration_seconds: number | null;
  size_bytes: number | null;
  video_stream_count: number;
  audio_stream_count: number;
  subtitle_stream_count: number;
  is_4k: boolean;
};

export type ProbeSnapshotDetail = ProbeSnapshotSummary & {
  payload: Record<string, unknown>;
};

export type PlanSnapshotSummary = {
  id: string;
  tracked_file_id: string;
  probe_snapshot_id: string;
  action: string;
  confidence: string;
  policy_version: number;
  profile_name: string | null;
  is_already_compliant: boolean;
  should_treat_as_protected: boolean;
  created_at: string;
  reason_codes: string[];
  warning_codes: string[];
  selected_audio_stream_indices: number[];
  selected_subtitle_stream_indices: number[];
};

export type PlanSnapshotDetail = PlanSnapshotSummary & {
  reasons: Array<Record<string, unknown>>;
  warnings: Array<Record<string, unknown>>;
  selected_streams: Record<string, unknown>;
  payload: Record<string, unknown>;
};

export type FileListResponse = {
  items: FileSummary[];
  limit: number | null;
  offset: number;
};

export type ProbeFileResponse = {
  tracked_file: FileSummary;
  latest_probe_snapshot: ProbeSnapshotDetail;
};

export type PlanFileResponse = {
  tracked_file: FileSummary;
  latest_probe_snapshot: ProbeSnapshotDetail;
  latest_plan_snapshot: PlanSnapshotDetail;
};

export type FolderBrowseEntry = {
  name: string;
  path: string;
  entry_type: string;
  is_video: boolean;
};

export type FolderBrowseResponse = {
  root_path: string;
  current_path: string;
  parent_path: string | null;
  entries: FolderBrowseEntry[];
};

export type FolderScanSummary = {
  folder_path: string;
  root_path: string;
  directory_count: number;
  direct_directory_count: number;
  video_file_count: number;
  likely_show_count: number;
  likely_season_count: number;
  likely_episode_count: number;
  likely_film_count: number;
  files: FolderBrowseEntry[];
};

export type DryRunItem = {
  source_path: string;
  file_name: string;
  action: string;
  confidence: string;
  requires_review: boolean;
  is_protected: boolean;
  reason_codes: string[];
  warning_codes: string[];
  selected_audio_stream_indices: number[];
  selected_subtitle_stream_indices: number[];
};

export type DryRunBatchResponse = {
  mode: string;
  scope: string;
  total_files: number;
  protected_count: number;
  review_count: number;
  actions: CountByValue[];
  items: DryRunItem[];
};

export type BatchPlanItem = {
  tracked_file: FileSummary;
  latest_probe_snapshot: ProbeSnapshotDetail;
  latest_plan_snapshot: PlanSnapshotDetail;
};

export type BatchPlanResponse = {
  scope: string;
  total_files: number;
  actions: CountByValue[];
  items: BatchPlanItem[];
};

export type JobSummary = {
  id: string;
  tracked_file_id: string;
  plan_snapshot_id: string;
  source_path: string | null;
  source_filename: string | null;
  worker_name: string | null;
  status: string;
  attempt_count: number;
  started_at: string | null;
  completed_at: string | null;
  progress_stage: string | null;
  progress_percent: number | null;
  progress_out_time_seconds: number | null;
  progress_fps: number | null;
  progress_speed: number | null;
  progress_updated_at: string | null;
  requested_execution_backend: string | null;
  actual_execution_backend: string | null;
  actual_execution_accelerator: string | null;
  backend_fallback_used: boolean;
  backend_selection_reason: string | null;
  failure_message: string | null;
  failure_category: string | null;
  verification_status: string;
  replacement_status: string;
  tracked_file_is_protected: boolean | null;
  requires_review: boolean;
  review_status: string | null;
  input_size_bytes: number | null;
  output_size_bytes: number | null;
  space_saved_bytes: number | null;
  video_input_size_bytes: number | null;
  video_output_size_bytes: number | null;
  video_space_saved_bytes: number | null;
  non_video_space_saved_bytes: number | null;
  compression_reduction_percent: number | null;
  created_at: string;
  updated_at: string;
};

export type JobDetail = JobSummary & {
  output_path: string | null;
  final_output_path: string | null;
  original_backup_path: string | null;
  execution_command: string[] | null;
  execution_stdout: string | null;
  execution_stderr: string | null;
  verification_payload: Record<string, unknown> | null;
  replacement_payload: Record<string, unknown> | null;
  replacement_failure_message: string | null;
  replace_in_place: boolean;
  require_verification: boolean;
  keep_original_until_verified: boolean;
  delete_replaced_source: boolean;
};

export type JobListResponse = {
  items: JobSummary[];
  limit: number | null;
  offset: number;
};

export type BatchJobItem = {
  source_path: string;
  status: string;
  message: string | null;
  job: JobDetail | null;
};

export type BatchJobCreateResponse = {
  scope: string;
  total_files: number;
  created_count: number;
  blocked_count: number;
  items: BatchJobItem[];
};

export type BinaryStatus = {
  configured_path: string;
  discoverable: boolean;
  exists: boolean;
  executable: boolean;
  status: string;
  message: string;
};

export type DevicePathStatus = {
  path: string;
  exists: boolean;
  readable: boolean;
  writable: boolean;
  is_character_device: boolean;
  status: string;
  message: string;
  vendor_id: string | null;
  vendor_name: string | null;
};

export type ExecutionBackendStatus = {
  backend: string;
  preference_key: string;
  detected: boolean;
  usable_by_ffmpeg: boolean;
  ffmpeg_path_verified: boolean;
  status: string;
  message: string;
  reason_unavailable: string | null;
  recommended_usage: string | null;
  device_paths: DevicePathStatus[];
  details: Record<string, unknown>;
};

export type ExecutionPreferences = {
  preferred_backend: string;
  allow_cpu_fallback: boolean;
};

export type QueueHealthSummary = {
  status: string;
  summary: string;
  pending_count: number;
  running_count: number;
  failed_count: number;
  manual_review_count: number;
  completed_count: number;
  oldest_pending_age_seconds: number | null;
  last_completed_age_seconds: number | null;
  recent_failed_count: number;
  recent_manual_review_count: number;
};

export type WorkerRunOnceResponse = {
  processed_job: boolean;
  job_id: string | null;
  final_status: string | null;
  failure_message: string | null;
  started_at: string | null;
  completed_at: string | null;
};

export type WorkerStatus = {
  status: string;
  summary: string;
  worker_name: string;
  mode: string;
  local_only: boolean;
  enabled: boolean;
  available: boolean;
  eligible: boolean;
  eligibility_summary: string;
  default_queue: string;
  ffmpeg: BinaryStatus;
  ffprobe: BinaryStatus;
  local_worker_queue: string;
  last_run_started_at: string | null;
  last_run_completed_at: string | null;
  last_processed_job_id: string | null;
  last_result_status: string | null;
  last_failure_message: string | null;
  processed_jobs: number;
  current_job_id: string | null;
  current_backend: string | null;
  current_stage: string | null;
  current_progress_percent: number | null;
  current_progress_updated_at: string | null;
  telemetry: Record<string, unknown> | null;
  capabilities: Record<string, boolean>;
  execution_backends: string[];
  hardware_acceleration: string[];
  hardware_probes: ExecutionBackendStatus[];
  runtime_device_paths: DevicePathStatus[];
  execution_preferences: ExecutionPreferences;
  scratch_path: Record<string, unknown>;
  media_paths: Array<Record<string, unknown>>;
  queue_health: QueueHealthSummary;
  self_test_available: boolean;
};

export type PathStatus = {
  role: string;
  display_name: string;
  path: string;
  status: string;
  issue_code: string;
  message: string;
  recommended_action: string | null;
  exists: boolean;
  is_directory: boolean;
  is_mount: boolean;
  readable: boolean;
  writable: boolean;
  same_filesystem_as_root: boolean | null;
  entry_count: number | null;
  total_space_bytes: number | null;
  free_space_bytes: number | null;
  free_space_ratio: number | null;
};

export type StorageStatus = {
  status: string;
  summary: string;
  standard_media_root: string;
  scratch: PathStatus;
  data_dir: PathStatus;
  media_mounts: PathStatus[];
  warnings: string[];
};

export type RuntimeStatus = {
  status: string;
  summary: string;
  version: string;
  environment: string;
  db_reachable: boolean;
  schema_reachable: boolean;
  auth_enabled: boolean;
  api_base_path: string;
  standard_media_root: string;
  scratch_dir: string;
  data_dir: string;
  media_mounts: string[];
  local_worker_enabled: boolean;
  first_user_setup_required: boolean;
  storage_setup_incomplete: boolean;
  user_count: number | null;
  config_sources: Record<string, string>;
  warnings: string[];
  execution_backends: ExecutionBackendStatus[];
  runtime_device_paths: DevicePathStatus[];
  execution_preferences: ExecutionPreferences;
  queue_health: QueueHealthSummary;
};

export type UpdateStatus = {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  channel: string;
  status: string;
  release_name: string | null;
  release_summary: string | null;
  breaking_changes_summary: string | null;
  checked_at: string | null;
  error: string | null;
  download_url: string | null;
  release_notes_url: string | null;
};

export type WorkerSelfTestCheck = {
  code: string;
  status: string;
  message: string;
};

export type WorkerSelfTestResponse = {
  status: string;
  summary: string;
  worker_name: string;
  started_at: string;
  completed_at: string;
  checks: WorkerSelfTestCheck[];
};

export type WorkerCapabilitySummary = {
  execution_modes: string[];
  supported_video_codecs: string[];
  supported_audio_codecs: string[];
  hardware_hints: string[];
  binary_support: Record<string, boolean>;
  max_concurrent_jobs: number | null;
  tags: string[];
};

export type WorkerHostSummary = {
  hostname: string | null;
  platform: string | null;
  agent_version: string | null;
  python_version: string | null;
};

export type WorkerRuntimeSummary = {
  queue: string | null;
  scratch_dir: string | null;
  media_mounts: string[];
  preferred_backend: string | null;
  allow_cpu_fallback: boolean | null;
  current_job_id: string | null;
  current_backend: string | null;
  current_stage: string | null;
  current_progress_percent: number | null;
  current_progress_updated_at: string | null;
  telemetry: Record<string, unknown> | null;
  last_completed_job_id: string | null;
};

export type WorkerBinarySummary = {
  name: string;
  configured_path: string | null;
  discoverable: boolean | null;
  message: string | null;
};

export type WorkerInventorySummary = {
  id: string;
  worker_key: string;
  display_name: string;
  worker_type: string;
  source: string;
  enabled: boolean;
  registration_status: string;
  health_status: string;
  health_summary: string | null;
  last_seen_at: string | null;
  last_heartbeat_at: string | null;
  last_registration_at: string | null;
  capability_summary: WorkerCapabilitySummary;
  host_summary: WorkerHostSummary;
  pending_assignment_count: number;
  last_completed_job_id: string | null;
};

export type WorkerInventoryDetail = WorkerInventorySummary & {
  runtime_summary: WorkerRuntimeSummary | null;
  binary_summary: WorkerBinarySummary[];
  assigned_job_ids: string[];
  last_processed_job_id: string | null;
  recent_failure_message: string | null;
  recent_jobs: Array<{
    job_id: string;
    source_filename: string | null;
    status: string;
    actual_execution_backend: string | null;
    requested_execution_backend: string | null;
    backend_fallback_used: boolean;
    completed_at: string | null;
    duration_seconds: number | null;
    failure_message: string | null;
  }>;
};

export type WorkerInventoryListResponse = {
  items: WorkerInventorySummary[];
};

export type WorkerStateChangeResponse = {
  worker: WorkerInventoryDetail;
  status: string;
};

export type ReviewReason = {
  code: string;
  message: string;
  kind: string;
};

export type ProtectedStateSummary = {
  is_protected: boolean;
  planner_protected: boolean;
  operator_protected: boolean;
  source: string;
  reason_codes: string[];
  note: string | null;
  updated_at: string | null;
  updated_by_username: string | null;
};

export type ReviewDecisionSummary = {
  id: string;
  decision_type: string;
  note: string | null;
  created_at: string;
  created_by_user_id: string;
  created_by_username: string;
};

export type ReviewItemSummary = {
  id: string;
  source_path: string;
  review_status: string;
  requires_review: boolean;
  confidence: string | null;
  tracked_file: FileSummary;
  latest_plan: PlanSnapshotSummary | null;
  latest_job: JobSummary | null;
  protected_state: ProtectedStateSummary;
  reasons: ReviewReason[];
  warnings: ReviewReason[];
  latest_probe_at: string | null;
  latest_plan_at: string | null;
  latest_job_at: string | null;
  latest_decision: ReviewDecisionSummary | null;
};

export type ReviewItemDetail = ReviewItemSummary & {
  latest_probe_snapshot_id: string | null;
  latest_plan_snapshot_id: string | null;
  latest_job_id: string | null;
};

export type ReviewListResponse = {
  items: ReviewItemSummary[];
  limit: number | null;
  offset: number;
};

export type ReviewDecisionPayload = {
  note?: string;
};

export type ReviewDecisionResponse = {
  review_item: ReviewItemDetail;
  decision: ReviewDecisionSummary | null;
  job: JobDetail | null;
};

export type AuthConfigSummary = {
  enabled: boolean;
  session_mode: string;
  access_token_ttl_minutes: number;
  refresh_token_ttl_days: number;
  access_token_algorithm: string;
};

export type OutputConfigSummary = {
  return_to_original_folder: boolean;
  default_container: string;
};

export type PolicyAudioSummary = {
  keep_languages: string[];
  preserve_best_surround: boolean;
  preserve_atmos_capable: boolean;
  preferred_codecs: string[];
  allow_commentary: boolean;
  max_tracks_to_keep: number;
};

export type PolicySubtitleSummary = {
  keep_languages: string[];
  keep_forced_languages: string[];
  keep_commentary: boolean;
  keep_hearing_impaired: boolean;
};

export type PolicyVideoSummary = {
  output_container: string;
  non_4k_preferred_codec: string;
  non_4k_allow_transcode: boolean;
  non_4k_max_video_bitrate_mbps: number;
  non_4k_max_width: number;
  four_k_mode: string;
  four_k_preserve_original_video: boolean;
  four_k_remove_non_english_audio: boolean;
  four_k_remove_non_english_subtitles: boolean;
};

export type WorkerDefinitionSummary = {
  id: string;
  type: string;
  enabled: boolean;
  queue: string;
  host_or_endpoint: string;
  max_concurrent_jobs: number;
  capabilities: Record<string, boolean>;
};

export type ProfileSummary = {
  name: string;
  description: string | null;
  source_path: string;
  path_prefixes: string[];
};

export type ConfigSourceFile = {
  requested_path: string;
  resolved_path: string;
  used_example_fallback: boolean;
  from_environment: boolean;
};

export type EffectiveConfig = {
  app_name: string;
  environment: string;
  timezone: string;
  scratch_dir: string;
  data_dir: string;
  output: OutputConfigSummary;
  auth: AuthConfigSummary;
  policy_version: number;
  policy_name: string;
  profile_names: string[];
  audio: PolicyAudioSummary;
  subtitles: PolicySubtitleSummary;
  video: PolicyVideoSummary;
  workers: WorkerDefinitionSummary[];
  profiles: ProfileSummary[];
  sources: Record<string, ConfigSourceFile>;
};

export type LibraryRoots = {
  media_root: string;
  movies_root: string | null;
  tv_root: string | null;
};

export type ExecutionPreferencesResponse = ExecutionPreferences;

export type ProcessingRuleValues = {
  target_video_codec: string;
  output_container: string;
  preferred_audio_languages: string[];
  keep_only_preferred_audio_languages: boolean;
  keep_forced_subtitles: boolean;
  keep_one_full_preferred_subtitle: boolean;
  drop_other_subtitles: boolean;
  preserve_surround: boolean;
  preserve_seven_one: boolean;
  preserve_atmos: boolean;
  preferred_subtitle_languages: string[];
  handling_mode: string;
  target_quality_mode: string;
  max_allowed_video_reduction_percent: number;
};

export type ProcessingRuleset = {
  profile_name: string | null;
  current: ProcessingRuleValues;
  defaults: ProcessingRuleValues;
  uses_defaults: boolean;
};

export type ProcessingRules = {
  movies: ProcessingRuleset;
  movies_4k: ProcessingRuleset;
  tv: ProcessingRuleset;
  tv_4k: ProcessingRuleset;
};

export type LoginPayload = {
  username: string;
  password: string;
};

export type ProbeOrPlanPayload = {
  source_path: string;
};

export type FileSelectionPayload = {
  source_path?: string;
  folder_path?: string;
  selected_paths?: string[];
};

export type CreateJobPayload = {
  tracked_file_id?: string;
  plan_snapshot_id?: string;
};

export type CreateBatchJobsPayload = FileSelectionPayload;

export type CountByValue = {
  value: string;
  count: number;
};

export type AnalyticsOverview = {
  total_tracked_files: number;
  files_by_lifecycle: CountByValue[];
  files_by_compliance: CountByValue[];
  total_jobs: number;
  jobs_by_status: CountByValue[];
  plans_by_action: CountByValue[];
  verification_outcomes: CountByValue[];
  replacement_outcomes: CountByValue[];
  processed_under_current_policy_count: number;
  protected_file_count: number;
  four_k_file_count: number;
};

export type ActionStorageSummary = {
  action: string;
  job_count: number;
  space_saved_bytes: number;
  average_space_saved_bytes: number | null;
};

export type AnalyticsStorage = {
  total_original_size_bytes: number;
  total_output_size_bytes: number;
  total_space_saved_bytes: number;
  average_space_saved_bytes: number | null;
  measurable_job_count: number;
  measurable_completed_job_count: number;
  savings_by_action: ActionStorageSummary[];
};

export type FailureCategory = {
  category: string;
  count: number;
  sample_message: string | null;
};

export type RecentOutcome = {
  job_id: string;
  tracked_file_id: string;
  file_name: string;
  status: string;
  action: string;
  updated_at: string;
  failure_category: string | null;
  failure_message: string | null;
};

export type AnalyticsOutcomes = {
  jobs_by_status: CountByValue[];
  verification_outcomes: CountByValue[];
  replacement_outcomes: CountByValue[];
  top_failure_categories: FailureCategory[];
  recent_outcomes: RecentOutcome[];
};

export type ResolutionActionBreakdown = {
  resolution: string;
  actions: CountByValue[];
};

export type AnalyticsMedia = {
  latest_probe_count: number;
  latest_plan_count: number;
  latest_probe_english_audio_count: number;
  latest_probe_forced_english_subtitle_count: number;
  latest_plan_forced_subtitle_intent_count: number;
  latest_plan_surround_preservation_intent_count: number;
  latest_plan_atmos_preservation_intent_count: number;
  action_breakdown_by_resolution: ResolutionActionBreakdown[];
  container_distribution: CountByValue[];
  video_codec_distribution: CountByValue[];
};

export type RecentAnalytics = {
  recent_completed_jobs: RecentOutcome[];
  recent_failed_jobs: RecentOutcome[];
};

export type AnalyticsDashboard = {
  overview: AnalyticsOverview;
  storage: AnalyticsStorage;
  outcomes: AnalyticsOutcomes;
  media: AnalyticsMedia;
  recent: RecentAnalytics;
};
