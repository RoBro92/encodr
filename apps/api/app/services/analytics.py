from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.analytics import (
    ActionStorageSummaryResponse,
    AnalyticsDashboardResponse,
    AnalyticsMediaResponse,
    AnalyticsOutcomesResponse,
    AnalyticsOverviewResponse,
    AnalyticsStorageResponse,
    CountByValueResponse,
    FailureCategoryResponse,
    RecentAnalyticsResponse,
    RecentOutcomeResponse,
    ResolutionActionBreakdownResponse,
)
from encodr_core.config import ConfigBundle
from encodr_db.models import Job
from encodr_db.repositories import AnalyticsRepository


class AnalyticsService:
    def __init__(self, *, config_bundle: ConfigBundle) -> None:
        self.config_bundle = config_bundle

    def overview(self, session: Session) -> AnalyticsOverviewResponse:
        repository = AnalyticsRepository(session)
        processing = repository.summarise_processing_history()
        return AnalyticsOverviewResponse(
            total_tracked_files=repository.count_tracked_files(),
            files_by_lifecycle=self._count_items(repository.count_files_by_lifecycle()),
            files_by_compliance=self._count_items(repository.count_files_by_compliance()),
            total_jobs=repository.count_jobs(),
            processed_file_count=processing.processed_file_count,
            average_processed_per_day=processing.average_processed_per_day,
            jobs_by_status=self._count_items(repository.count_jobs_by_status()),
            plans_by_action=self._count_items(repository.count_plans_by_action()),
            verification_outcomes=self._count_items(repository.count_verification_outcomes()),
            replacement_outcomes=self._count_items(repository.count_replacement_outcomes()),
            processed_under_current_policy_count=repository.count_processed_under_policy(
                self.config_bundle.policy.version
            ),
            protected_file_count=repository.count_protected_files(),
            four_k_file_count=repository.count_four_k_files(),
        )

    def storage(self, session: Session) -> AnalyticsStorageResponse:
        summary = AnalyticsRepository(session).summarise_storage_outcomes()
        return AnalyticsStorageResponse(
            total_original_size_bytes=summary.total_original_size_bytes,
            total_output_size_bytes=summary.total_output_size_bytes,
            total_space_saved_bytes=summary.total_space_saved_bytes,
            average_space_saved_bytes=summary.average_space_saved_bytes,
            average_space_saved_per_day_bytes=summary.average_space_saved_per_day_bytes,
            measurable_job_count=summary.measurable_job_count,
            measurable_completed_job_count=summary.measurable_completed_job_count,
            savings_by_action=[
                ActionStorageSummaryResponse(
                    action=action,
                    job_count=int(values["job_count"] or 0),
                    space_saved_bytes=int(values["space_saved_bytes"] or 0),
                    average_space_saved_bytes=(
                        int(values["average_space_saved_bytes"])
                        if values["average_space_saved_bytes"] is not None
                        else None
                    ),
                )
                for action, values in summary.savings_by_action.items()
            ],
        )

    def outcomes(self, session: Session) -> AnalyticsOutcomesResponse:
        repository = AnalyticsRepository(session)
        return AnalyticsOutcomesResponse(
            jobs_by_status=self._count_items(repository.count_jobs_by_status()),
            verification_outcomes=self._count_items(repository.count_verification_outcomes()),
            replacement_outcomes=self._count_items(repository.count_replacement_outcomes()),
            top_failure_categories=[
                FailureCategoryResponse(**item)
                for item in repository.top_failure_categories()
            ],
            recent_outcomes=[self._recent_item(job) for job in repository.recent_jobs(limit=10)],
        )

    def media(self, session: Session) -> AnalyticsMediaResponse:
        repository = AnalyticsRepository(session)
        processing = repository.summarise_processing_history()
        latest_probes = repository.list_latest_probe_snapshots()
        latest_plans = repository.list_latest_plan_snapshots()

        container_counts: dict[str, int] = {}
        video_codec_counts: dict[str, int] = {}
        english_audio_count = 0
        forced_subtitle_count = 0
        forced_intent_count = 0
        surround_intent_count = 0
        atmos_intent_count = 0

        for snapshot in latest_probes:
            payload = snapshot.payload
            container = (
                payload.get("extension")
                or payload.get("container", {}).get("extension")
                or payload.get("container", {}).get("format_name")
                or "unknown"
            )
            video_codec = (
                payload.get("video_streams", [{}])[0].get("codec_name")
                if payload.get("video_streams")
                else "unknown"
            )
            container_counts[str(container)] = container_counts.get(str(container), 0) + 1
            video_codec_counts[str(video_codec)] = video_codec_counts.get(str(video_codec), 0) + 1
            if payload.get("has_english_audio"):
                english_audio_count += 1
            if payload.get("has_forced_english_subtitle"):
                forced_subtitle_count += 1

        for snapshot in latest_plans:
            payload = snapshot.payload
            subtitles = payload.get("subtitles", {})
            audio = payload.get("audio", {})
            if subtitles.get("forced_stream_indices"):
                forced_intent_count += 1
            if audio.get("preserved_surround_stream_indices"):
                surround_intent_count += 1
            if audio.get("preserved_atmos_stream_indices"):
                atmos_intent_count += 1

        action_by_resolution = repository.action_breakdown_by_four_k()
        return AnalyticsMediaResponse(
            latest_probe_count=len(latest_probes),
            latest_plan_count=len(latest_plans),
            total_audio_tracks_removed=processing.total_audio_tracks_removed,
            total_subtitle_tracks_removed=processing.total_subtitle_tracks_removed,
            latest_probe_english_audio_count=english_audio_count,
            latest_probe_forced_english_subtitle_count=forced_subtitle_count,
            latest_plan_forced_subtitle_intent_count=forced_intent_count,
            latest_plan_surround_preservation_intent_count=surround_intent_count,
            latest_plan_atmos_preservation_intent_count=atmos_intent_count,
            action_breakdown_by_resolution=[
                ResolutionActionBreakdownResponse(
                    resolution="4K" if resolution == "4k" else "Non-4K",
                    actions=self._count_items(actions),
                )
                for resolution, actions in action_by_resolution.items()
            ],
            container_distribution=self._count_items(container_counts),
            video_codec_distribution=self._count_items(video_codec_counts),
        )

    def recent(self, session: Session) -> RecentAnalyticsResponse:
        repository = AnalyticsRepository(session)
        return RecentAnalyticsResponse(
            recent_completed_jobs=[
                self._recent_item(job) for job in repository.recent_completed_jobs(limit=5)
            ],
            recent_failed_jobs=[
                self._recent_item(job) for job in repository.recent_failed_jobs(limit=5)
            ],
        )

    def dashboard(self, session: Session) -> AnalyticsDashboardResponse:
        return AnalyticsDashboardResponse(
            overview=self.overview(session),
            storage=self.storage(session),
            outcomes=self.outcomes(session),
            media=self._dashboard_media(session),
            recent=self.recent(session),
        )

    def _dashboard_media(self, session: Session) -> AnalyticsMediaResponse:
        repository = AnalyticsRepository(session)
        processing = repository.summarise_processing_history()
        return AnalyticsMediaResponse(
            latest_probe_count=0,
            latest_plan_count=0,
            total_audio_tracks_removed=processing.total_audio_tracks_removed,
            total_subtitle_tracks_removed=processing.total_subtitle_tracks_removed,
            latest_probe_english_audio_count=0,
            latest_probe_forced_english_subtitle_count=0,
            latest_plan_forced_subtitle_intent_count=0,
            latest_plan_surround_preservation_intent_count=0,
            latest_plan_atmos_preservation_intent_count=0,
            action_breakdown_by_resolution=[],
            container_distribution=[],
            video_codec_distribution=[],
        )

    def _count_items(self, counts: dict[str, int]) -> list[CountByValueResponse]:
        return [
            CountByValueResponse(value=value, count=count)
            for value, count in sorted(counts.items(), key=lambda item: item[0])
        ]

    def _recent_item(self, job: Job) -> RecentOutcomeResponse:
        return RecentOutcomeResponse(
            job_id=job.id,
            tracked_file_id=job.tracked_file_id,
            file_name=job.tracked_file.source_filename if job.tracked_file is not None else job.tracked_file_id,
            status=job.status.value,
            action=job.plan_snapshot.action.value if job.plan_snapshot is not None else "unknown",
            updated_at=job.updated_at,
            failure_category=job.failure_category,
            failure_message=job.failure_message,
        )
