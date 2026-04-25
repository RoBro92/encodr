from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CountByValueResponse(BaseModel):
    value: str
    count: int


class AnalyticsOverviewResponse(BaseModel):
    total_tracked_files: int
    files_by_lifecycle: list[CountByValueResponse]
    files_by_compliance: list[CountByValueResponse]
    total_jobs: int
    processed_file_count: int
    average_processed_per_day: float | None = None
    jobs_by_status: list[CountByValueResponse]
    plans_by_action: list[CountByValueResponse]
    verification_outcomes: list[CountByValueResponse]
    replacement_outcomes: list[CountByValueResponse]
    processed_under_current_policy_count: int
    protected_file_count: int
    four_k_file_count: int


class ActionStorageSummaryResponse(BaseModel):
    action: str
    job_count: int
    space_saved_bytes: int
    average_space_saved_bytes: int | None = None


class AnalyticsStorageResponse(BaseModel):
    total_original_size_bytes: int
    total_output_size_bytes: int
    total_space_saved_bytes: int
    average_space_saved_bytes: int | None = None
    average_space_saved_per_day_bytes: int | None = None
    measurable_job_count: int
    measurable_completed_job_count: int
    savings_by_action: list[ActionStorageSummaryResponse]


class FailureCategoryResponse(BaseModel):
    category: str
    count: int
    sample_message: str | None = None


class RecentOutcomeResponse(BaseModel):
    job_id: str
    tracked_file_id: str
    file_name: str
    status: str
    action: str
    updated_at: datetime
    failure_category: str | None = None
    failure_message: str | None = None


class AnalyticsOutcomesResponse(BaseModel):
    jobs_by_status: list[CountByValueResponse]
    verification_outcomes: list[CountByValueResponse]
    replacement_outcomes: list[CountByValueResponse]
    top_failure_categories: list[FailureCategoryResponse]
    recent_outcomes: list[RecentOutcomeResponse]


class ResolutionActionBreakdownResponse(BaseModel):
    resolution: str
    actions: list[CountByValueResponse]


class AnalyticsMediaResponse(BaseModel):
    latest_probe_count: int
    latest_plan_count: int
    total_audio_tracks_removed: int = 0
    total_subtitle_tracks_removed: int = 0
    latest_probe_english_audio_count: int
    latest_probe_forced_english_subtitle_count: int
    latest_plan_forced_subtitle_intent_count: int
    latest_plan_surround_preservation_intent_count: int
    latest_plan_atmos_preservation_intent_count: int
    action_breakdown_by_resolution: list[ResolutionActionBreakdownResponse]
    container_distribution: list[CountByValueResponse]
    video_codec_distribution: list[CountByValueResponse]


class RecentAnalyticsResponse(BaseModel):
    recent_completed_jobs: list[RecentOutcomeResponse]
    recent_failed_jobs: list[RecentOutcomeResponse]


class AnalyticsDashboardResponse(BaseModel):
    overview: AnalyticsOverviewResponse
    storage: AnalyticsStorageResponse
    outcomes: AnalyticsOutcomesResponse
    media: AnalyticsMediaResponse
    recent: RecentAnalyticsResponse
