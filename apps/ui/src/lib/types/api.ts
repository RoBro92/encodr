export type AuthTokens = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  access_token_expires_in: number;
  refresh_token_expires_in: number;
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

export type JobSummary = {
  id: string;
  tracked_file_id: string;
  plan_snapshot_id: string;
  worker_name: string | null;
  status: string;
  attempt_count: number;
  started_at: string | null;
  completed_at: string | null;
  failure_message: string | null;
  verification_status: string;
  replacement_status: string;
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

export type BinaryStatus = {
  configured_path: string;
  discoverable: boolean;
  exists: boolean;
  executable: boolean;
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
  worker_name: string;
  local_only: boolean;
  default_queue: string;
  ffmpeg: BinaryStatus;
  ffprobe: BinaryStatus;
  local_worker_enabled: boolean;
  local_worker_queue: string;
  last_run_started_at: string | null;
  last_run_completed_at: string | null;
  last_processed_job_id: string | null;
  last_result_status: string | null;
  last_failure_message: string | null;
  processed_jobs: number;
  capabilities: Record<string, boolean>;
};

export type PathStatus = {
  path: string;
  exists: boolean;
  is_directory: boolean;
  readable: boolean;
  writable: boolean;
};

export type StorageStatus = {
  scratch: PathStatus;
  data_dir: PathStatus;
  media_mounts: PathStatus[];
};

export type RuntimeStatus = {
  version: string;
  environment: string;
  db_reachable: boolean;
  auth_enabled: boolean;
  api_base_path: string;
  scratch_dir: string;
  data_dir: string;
  media_mounts: string[];
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

export type LoginPayload = {
  username: string;
  password: string;
};

export type ProbeOrPlanPayload = {
  source_path: string;
};

export type CreateJobPayload = {
  tracked_file_id?: string;
  plan_snapshot_id?: string;
};
