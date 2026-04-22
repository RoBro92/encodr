from __future__ import annotations

from pydantic import BaseModel


class AuthConfigSummaryResponse(BaseModel):
    enabled: bool
    session_mode: str
    access_token_ttl_minutes: int
    refresh_token_ttl_days: int
    access_token_algorithm: str


class OutputConfigSummaryResponse(BaseModel):
    return_to_original_folder: bool
    default_container: str


class PolicyAudioSummaryResponse(BaseModel):
    keep_languages: list[str]
    preserve_best_surround: bool
    preserve_atmos_capable: bool
    preferred_codecs: list[str]
    allow_commentary: bool
    max_tracks_to_keep: int


class PolicySubtitleSummaryResponse(BaseModel):
    keep_languages: list[str]
    keep_forced_languages: list[str]
    keep_commentary: bool
    keep_hearing_impaired: bool


class PolicyVideoSummaryResponse(BaseModel):
    output_container: str
    non_4k_preferred_codec: str
    non_4k_allow_transcode: bool
    non_4k_max_video_bitrate_mbps: int
    non_4k_max_width: int
    four_k_mode: str
    four_k_preserve_original_video: bool
    four_k_remove_non_english_audio: bool
    four_k_remove_non_english_subtitles: bool


class ProfileSummaryResponse(BaseModel):
    name: str
    description: str | None = None
    source_path: str
    path_prefixes: list[str]


class WorkerDefinitionSummaryResponse(BaseModel):
    id: str
    type: str
    enabled: bool
    queue: str
    host_or_endpoint: str
    max_concurrent_jobs: int
    capabilities: dict[str, bool]


class ConfigSourceFileResponse(BaseModel):
    requested_path: str
    resolved_path: str
    used_example_fallback: bool
    from_environment: bool


class EffectiveConfigResponse(BaseModel):
    app_name: str
    environment: str
    timezone: str
    scratch_dir: str
    data_dir: str
    output: OutputConfigSummaryResponse
    auth: AuthConfigSummaryResponse
    policy_version: int
    policy_name: str
    profile_names: list[str]
    audio: PolicyAudioSummaryResponse
    subtitles: PolicySubtitleSummaryResponse
    video: PolicyVideoSummaryResponse
    workers: list[WorkerDefinitionSummaryResponse]
    profiles: list[ProfileSummaryResponse]
    sources: dict[str, ConfigSourceFileResponse]


class LibraryRootsResponse(BaseModel):
    media_root: str
    movies_root: str | None = None
    tv_root: str | None = None


class ExecutionPreferencesResponse(BaseModel):
    preferred_backend: str
    allow_cpu_fallback: bool


class ProcessingRuleValuesResponse(BaseModel):
    target_video_codec: str
    output_container: str
    preferred_audio_languages: list[str]
    keep_only_preferred_audio_languages: bool
    keep_forced_subtitles: bool
    keep_one_full_preferred_subtitle: bool
    drop_other_subtitles: bool
    preserve_surround: bool
    preserve_seven_one: bool
    preserve_atmos: bool
    preferred_subtitle_languages: list[str]
    handling_mode: str
    target_quality_mode: str
    max_allowed_video_reduction_percent: int


class ProcessingRulesetResponse(BaseModel):
    profile_name: str | None = None
    current: ProcessingRuleValuesResponse
    defaults: ProcessingRuleValuesResponse
    uses_defaults: bool


class ProcessingRulesResponse(BaseModel):
    movies: ProcessingRulesetResponse
    movies_4k: ProcessingRulesetResponse
    tv: ProcessingRulesetResponse
    tv_4k: ProcessingRulesetResponse
