from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.schemas.config import (
    AuthConfigSummaryResponse,
    ConfigSourceFileResponse,
    EffectiveConfigResponse,
    OutputConfigSummaryResponse,
    PolicyAudioSummaryResponse,
    PolicySubtitleSummaryResponse,
    PolicyVideoSummaryResponse,
    ProfileSummaryResponse,
    WorkerDefinitionSummaryResponse,
)
from app.schemas.worker import HealthStatus
from app.services.setup import SetupStateService
from encodr_core.config import ConfigBundle
from encodr_db.models import JobStatus
from encodr_db.repositories import JobRepository, UserRepository
from encodr_shared.worker_runtime import discover_runtime_devices, probe_execution_backends
from encodr_shared.update import UpdateChecker


class SystemService:
    STANDARD_MEDIA_ROOT = "/media"

    def __init__(
        self,
        *,
        config_bundle: ConfigBundle,
        session_factory: sessionmaker | Any | None,
        app_version: str,
    ) -> None:
        self.config_bundle = config_bundle
        self.session_factory = session_factory
        self.app_version = app_version

    def path_status(
        self,
        path: Path | str,
        *,
        role: str,
        writable_required: bool,
    ) -> dict[str, object]:
        resolved = Path(path)
        exists = resolved.exists()
        is_directory = resolved.is_dir()
        readable = os.access(resolved, os.R_OK)
        writable = os.access(resolved, os.W_OK)
        is_mount = resolved.is_mount() if exists and is_directory else False
        root_device_id = os.stat("/").st_dev if Path("/").exists() else None
        device_id = os.stat(resolved).st_dev if exists and is_directory else None
        same_filesystem_as_root = (
            bool(root_device_id is not None and device_id is not None and device_id == root_device_id)
            if exists and is_directory
            else None
        )
        entry_count: int | None = None
        total_space_bytes: int | None = None
        free_space_bytes: int | None = None
        free_space_ratio: float | None = None

        if exists and is_directory:
            try:
                entry_count = sum(1 for _ in resolved.iterdir())
            except OSError:
                entry_count = None
            try:
                usage = shutil.disk_usage(resolved)
                total_space_bytes = int(usage.total)
                free_space_bytes = int(usage.free)
                free_space_ratio = (
                    round(usage.free / usage.total, 4) if usage.total > 0 else None
                )
            except OSError:
                total_space_bytes = None
                free_space_bytes = None
                free_space_ratio = None

        display_name = {
            "scratch": "Scratch workspace",
            "data": "Application data",
            "media_mount": "Media library",
        }.get(role, role.replace("_", " ").title())

        recommended_action: str | None = None

        if not exists:
            status = HealthStatus.FAILED
            issue_code = "path_missing"
            if role == "media_mount":
                message = f"Media mount not found at {resolved.as_posix()}."
                recommended_action = (
                    f"Mount your library at {self.STANDARD_MEDIA_ROOT} inside the LXC, "
                    "then refresh the System page."
                )
            else:
                message = "The path does not exist."
                recommended_action = "Create the directory or correct the configured path."
        elif not is_directory:
            status = HealthStatus.FAILED
            issue_code = "not_directory"
            message = "The path exists but is not a directory."
            recommended_action = "Point Encodr at a directory instead of a file."
        elif not readable:
            status = HealthStatus.FAILED
            issue_code = "not_readable"
            if role == "media_mount":
                message = "Media path exists but is not readable."
                recommended_action = "Check the mount permissions from the LXC and Docker containers."
            else:
                message = "The path exists, but Encodr cannot read it."
                recommended_action = "Check the directory permissions for the Encodr runtime."
        elif writable_required and not writable:
            status = HealthStatus.DEGRADED
            issue_code = "not_writable"
            if role == "media_mount":
                message = "Media path exists but is not writable."
                recommended_action = "Grant write access if you want Encodr to replace files in place."
            else:
                message = "The path is readable, but Encodr cannot write to it."
                recommended_action = "Grant write access to the Encodr runtime user."
        elif role == "media_mount" and resolved.as_posix() == self.STANDARD_MEDIA_ROOT and entry_count == 0:
            status = HealthStatus.DEGRADED
            issue_code = "path_empty"
            message = "Media path is empty. If you expected a mounted library, check the host or LXC bind mount."
            recommended_action = "Confirm your library is mounted into /media, then refresh the System page."
        elif role == "media_mount" and resolved.as_posix() == self.STANDARD_MEDIA_ROOT and same_filesystem_as_root:
            status = HealthStatus.DEGRADED
            issue_code = "shares_root_filesystem"
            message = "Media path is available but appears to share the container root filesystem."
            recommended_action = "If you expected a mounted library, check the host share mount and LXC bind mount."
        elif role == "scratch" and resolved.as_posix().startswith("/temp") and same_filesystem_as_root:
            status = HealthStatus.DEGRADED
            issue_code = "shares_root_filesystem"
            message = "Scratch path is available but does not appear to be on a dedicated /temp mount."
            recommended_action = "If you expected a separate scratch disk, check the /temp mount inside the LXC."
        elif free_space_ratio is not None and free_space_ratio < 0.05:
            status = HealthStatus.FAILED
            issue_code = "low_space_critical"
            message = "Very little free space is available."
            recommended_action = "Free space before running more jobs."
        elif free_space_ratio is not None and free_space_ratio < 0.1:
            status = HealthStatus.DEGRADED
            issue_code = "low_space_warning"
            message = "Free space is getting low."
            recommended_action = "Plan for additional free space soon."
        else:
            status = HealthStatus.HEALTHY
            issue_code = "ok"
            if role == "media_mount":
                message = "The media library path is available."
            else:
                message = "The path is available."

        return {
            "role": role,
            "display_name": display_name,
            "path": resolved.as_posix(),
            "status": status,
            "issue_code": issue_code,
            "message": message,
            "recommended_action": recommended_action,
            "exists": exists,
            "is_directory": is_directory,
            "is_mount": is_mount,
            "readable": readable,
            "writable": writable,
            "same_filesystem_as_root": same_filesystem_as_root,
            "entry_count": entry_count,
            "total_space_bytes": total_space_bytes,
            "free_space_bytes": free_space_bytes,
            "free_space_ratio": free_space_ratio,
        }

    def db_reachable(self) -> bool:
        if self.session_factory is None:
            return False
        try:
            with self.session_factory() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def schema_reachable(self) -> bool:
        if self.session_factory is None:
            return False
        try:
            with self.session_factory() as session:
                UserRepository(session).count_users()
            return True
        except Exception:
            return False

    def user_count(self) -> int | None:
        if self.session_factory is None:
            return None
        try:
            with self.session_factory() as session:
                return UserRepository(session).count_users()
        except Exception:
            return None

    def queue_health_summary(self) -> dict[str, object]:
        if self.session_factory is None:
            return {
                "status": HealthStatus.UNKNOWN,
                "summary": "Queue state is unavailable.",
                "pending_count": 0,
                "running_count": 0,
                "failed_count": 0,
                "manual_review_count": 0,
                "completed_count": 0,
                "oldest_pending_age_seconds": None,
                "last_completed_age_seconds": None,
                "recent_failed_count": 0,
                "recent_manual_review_count": 0,
            }

        with self.session_factory() as session:
            repository = JobRepository(session)
            counts = repository.count_by_status()
            now = datetime.now(timezone.utc)
            oldest_pending = repository.oldest_created_at_for_status(JobStatus.PENDING)
            last_completed = repository.latest_completed_at()
            recent_window = now - timedelta(hours=24)
            recent_failed_count = repository.count_recent_statuses([JobStatus.FAILED], since=recent_window)
            recent_manual_review_count = repository.count_recent_statuses(
                [JobStatus.MANUAL_REVIEW],
                since=recent_window,
            )

        pending_count = counts.get(JobStatus.PENDING.value, 0)
        running_count = counts.get(JobStatus.RUNNING.value, 0)
        failed_count = counts.get(JobStatus.FAILED.value, 0)
        manual_review_count = counts.get(JobStatus.MANUAL_REVIEW.value, 0)
        completed_count = counts.get(JobStatus.COMPLETED.value, 0) + counts.get(JobStatus.SKIPPED.value, 0)
        oldest_pending_age_seconds = self.age_seconds(oldest_pending, now)
        last_completed_age_seconds = self.age_seconds(last_completed, now)

        if running_count > 0:
            status = HealthStatus.DEGRADED
            summary = "The local worker is currently processing jobs."
        elif failed_count > 0 or manual_review_count > 0:
            status = HealthStatus.DEGRADED
            summary = "Recent job history includes failures or manual review outcomes."
        elif pending_count > 10:
            status = HealthStatus.DEGRADED
            summary = "Pending jobs are building up."
        else:
            status = HealthStatus.HEALTHY
            summary = "Queue health is within expected bounds."

        return {
            "status": status,
            "summary": summary,
            "pending_count": pending_count,
            "running_count": running_count,
            "failed_count": failed_count,
            "manual_review_count": manual_review_count,
            "completed_count": completed_count,
            "oldest_pending_age_seconds": oldest_pending_age_seconds,
            "last_completed_age_seconds": last_completed_age_seconds,
            "recent_failed_count": recent_failed_count,
            "recent_manual_review_count": recent_manual_review_count,
        }

    def storage_status(self) -> dict[str, object]:
        scratch = self.path_status(
            self.config_bundle.app.scratch_dir,
            role="scratch",
            writable_required=True,
        )
        data_dir = self.path_status(
            self.config_bundle.app.data_dir,
            role="data",
            writable_required=True,
        )
        media_mounts = [
            self.path_status(path, role="media_mount", writable_required=True)
            for path in self.config_bundle.workers.local.media_mounts
        ]

        items = [scratch, data_dir, *media_mounts]
        warnings = [item["message"] for item in items if item["status"] != HealthStatus.HEALTHY]
        media_missing = any(
            item["role"] == "media_mount" and item["issue_code"] == "path_missing"
            for item in items
        )
        if media_missing:
            status = HealthStatus.FAILED
            summary = "Storage is not configured yet."
        elif any(item["status"] == HealthStatus.FAILED for item in items):
            status = HealthStatus.FAILED
            summary = "One or more configured paths are unavailable."
        elif any(item["status"] == HealthStatus.DEGRADED for item in items):
            status = HealthStatus.DEGRADED
            summary = "Storage is reachable but needs attention."
        else:
            status = HealthStatus.HEALTHY
            summary = "Configured storage paths are healthy."

        return {
            "status": status,
            "summary": summary,
            "standard_media_root": self.STANDARD_MEDIA_ROOT,
            "scratch": scratch,
            "data_dir": data_dir,
            "media_mounts": media_mounts,
            "warnings": warnings,
        }

    def runtime_status(self) -> dict[str, object]:
        db_reachable = self.db_reachable()
        schema_reachable = self.schema_reachable()
        user_count = self.user_count()
        queue_health = self.queue_health_summary()
        storage = self.storage_status()
        execution_backends = [
            {
                "backend": probe.backend,
                "preference_key": {
                    "cpu": "cpu_only",
                    "intel_igpu": "prefer_intel_igpu",
                    "nvidia_gpu": "prefer_nvidia_gpu",
                    "amd_gpu": "prefer_amd_gpu",
                }.get(probe.backend, probe.backend),
                "detected": probe.detected,
                "usable_by_ffmpeg": probe.usable,
                "ffmpeg_path_verified": bool(probe.details.get("ffmpeg_path_verified", probe.usable)),
                "status": probe.status,
                "message": probe.message,
                "reason_unavailable": probe.details.get("reason_unavailable"),
                "recommended_usage": probe.details.get("recommended_usage"),
                "device_paths": probe.details.get("device_paths", []),
                "details": probe.details,
            }
            for probe in probe_execution_backends(self.config_bundle.app.media.ffmpeg_path)
        ]
        runtime_device_paths = discover_runtime_devices()
        execution_preferences = SetupStateService(config_bundle=self.config_bundle).get_execution_preferences()
        first_user_setup_required = user_count == 0 if user_count is not None else False

        warnings: list[str] = []
        if not db_reachable:
            warnings.append("Database connectivity is unavailable.")
        if db_reachable and not schema_reachable:
            warnings.append("Database is reachable but the expected schema is unavailable.")
        if not self.config_bundle.workers.local.enabled:
            warnings.append("The local worker is disabled.")
        if storage["status"] != HealthStatus.HEALTHY:
            warnings.append(str(storage["summary"]))
        for backend in execution_backends:
            if backend["backend"] == "cpu":
                continue
            if backend["detected"] and not backend["usable_by_ffmpeg"]:
                warnings.append(str(backend["message"]))
                break
        if queue_health["status"] == HealthStatus.DEGRADED:
            warnings.append(str(queue_health["summary"]))

        if not db_reachable or not schema_reachable:
            status = HealthStatus.FAILED
            summary = "Runtime health checks failed."
        elif warnings:
            status = HealthStatus.DEGRADED
            summary = "Runtime health completed with warnings."
        else:
            status = HealthStatus.HEALTHY
            summary = "Runtime health is healthy."

        return {
            "status": status,
            "summary": summary,
            "version": self.app_version,
            "environment": self.config_bundle.app.environment.value,
            "db_reachable": db_reachable,
            "schema_reachable": schema_reachable,
            "auth_enabled": self.config_bundle.app.auth.enabled,
            "api_base_path": self.config_bundle.app.api.base_path,
            "standard_media_root": self.STANDARD_MEDIA_ROOT,
            "scratch_dir": self.config_bundle.app.scratch_dir.as_posix(),
            "data_dir": self.config_bundle.app.data_dir.as_posix(),
            "media_mounts": [path.as_posix() for path in self.config_bundle.workers.local.media_mounts],
            "local_worker_enabled": self.config_bundle.workers.local.enabled,
            "first_user_setup_required": first_user_setup_required,
            "storage_setup_incomplete": storage["status"] != HealthStatus.HEALTHY,
            "user_count": user_count,
            "config_sources": {
                "app": self.config_bundle.paths.app.resolved_path.as_posix(),
                "policy": self.config_bundle.paths.policy.resolved_path.as_posix(),
                "workers": self.config_bundle.paths.workers.resolved_path.as_posix(),
            },
            "warnings": warnings,
            "execution_backends": execution_backends,
            "runtime_device_paths": runtime_device_paths,
            "execution_preferences": execution_preferences,
            "queue_health": queue_health,
        }

    def update_status(self, update_checker: UpdateChecker, *, refresh: bool = False) -> dict[str, object]:
        result = update_checker.check_now() if refresh else update_checker.current_status(auto_check=True)
        return {
            "current_version": result.current_version,
            "latest_version": result.latest_version,
            "update_available": result.update_available,
            "channel": result.channel,
            "status": result.status,
            "release_name": result.release_name,
            "release_summary": result.release_summary,
            "breaking_changes_summary": getattr(result, "breaking_changes_summary", None),
            "checked_at": result.checked_at.isoformat() if result.checked_at else None,
            "error": result.error,
            "download_url": result.download_url,
            "release_notes_url": result.release_notes_url,
        }

    def effective_config(self) -> EffectiveConfigResponse:
        bundle = self.config_bundle
        profile_paths: dict[str, list[str]] = {name: [] for name in bundle.profiles}
        for override in bundle.policy.profiles.path_overrides:
            profile_paths.setdefault(override.profile, []).append(override.path_prefix)

        workers: list[WorkerDefinitionSummaryResponse] = [
            WorkerDefinitionSummaryResponse(
                id=bundle.workers.local.id,
                type=bundle.workers.local.type,
                enabled=bundle.workers.local.enabled,
                queue=bundle.workers.local.queue,
                host_or_endpoint=bundle.workers.local.host,
                max_concurrent_jobs=bundle.workers.local.max_concurrent_jobs,
                capabilities=bundle.workers.local.capabilities.model_dump(mode="json"),
            )
        ]
        for worker in bundle.workers.remote:
            workers.append(
                WorkerDefinitionSummaryResponse(
                    id=worker.id,
                    type=worker.type,
                    enabled=worker.enabled,
                    queue=worker.queue,
                    host_or_endpoint=str(worker.endpoint),
                    max_concurrent_jobs=worker.max_concurrent_jobs,
                    capabilities=worker.capabilities.model_dump(mode="json"),
                )
            )

        return EffectiveConfigResponse(
            app_name=bundle.app.name,
            environment=bundle.app.environment.value,
            timezone=bundle.app.timezone,
            scratch_dir=bundle.app.scratch_dir.as_posix(),
            data_dir=bundle.app.data_dir.as_posix(),
            output=OutputConfigSummaryResponse(
                return_to_original_folder=bundle.app.output.return_to_original_folder,
                default_container=bundle.app.output.default_container.value,
            ),
            auth=AuthConfigSummaryResponse(
                enabled=bundle.app.auth.enabled,
                session_mode=bundle.app.auth.session_mode.value,
                access_token_ttl_minutes=bundle.app.auth.access_token_ttl_minutes,
                refresh_token_ttl_days=bundle.app.auth.refresh_token_ttl_days,
                access_token_algorithm=bundle.app.auth.access_token_algorithm,
            ),
            policy_version=bundle.policy.version,
            policy_name=bundle.policy.name,
            profile_names=sorted(bundle.profiles.keys()),
            audio=PolicyAudioSummaryResponse(
                keep_languages=bundle.policy.audio.keep_languages,
                preserve_best_surround=bundle.policy.audio.preserve_best_surround,
                preserve_atmos_capable=bundle.policy.audio.preserve_atmos_capable,
                preferred_codecs=bundle.policy.audio.preferred_codecs,
                allow_commentary=bundle.policy.audio.allow_commentary,
                max_tracks_to_keep=bundle.policy.audio.max_tracks_to_keep,
            ),
            subtitles=PolicySubtitleSummaryResponse(
                keep_languages=bundle.policy.subtitles.keep_languages,
                keep_forced_languages=bundle.policy.subtitles.keep_forced_languages,
                keep_commentary=bundle.policy.subtitles.keep_commentary,
                keep_hearing_impaired=bundle.policy.subtitles.keep_hearing_impaired,
            ),
            video=PolicyVideoSummaryResponse(
                output_container=bundle.policy.video.output_container.value,
                non_4k_preferred_codec=bundle.policy.video.non_4k.preferred_codec.value,
                non_4k_allow_transcode=bundle.policy.video.non_4k.allow_transcode,
                non_4k_max_video_bitrate_mbps=bundle.policy.video.non_4k.max_video_bitrate_mbps,
                non_4k_max_width=bundle.policy.video.non_4k.max_width,
                four_k_mode=bundle.policy.video.four_k.mode.value,
                four_k_preserve_original_video=bundle.policy.video.four_k.preserve_original_video,
                four_k_remove_non_english_audio=bundle.policy.video.four_k.remove_non_english_audio,
                four_k_remove_non_english_subtitles=bundle.policy.video.four_k.remove_non_english_subtitles,
            ),
            workers=workers,
            profiles=[
                ProfileSummaryResponse(
                    name=name,
                    description=profile.description,
                    source_path=bundle.profile_sources[name].as_posix(),
                    path_prefixes=sorted(profile_paths.get(name, [])),
                )
                for name, profile in sorted(bundle.profiles.items())
            ],
            sources={
                "app": ConfigSourceFileResponse(
                    requested_path=bundle.paths.app.requested_path.as_posix(),
                    resolved_path=bundle.paths.app.resolved_path.as_posix(),
                    used_example_fallback=bundle.paths.app.used_example_fallback,
                    from_environment=bundle.paths.app.from_environment,
                ),
                "policy": ConfigSourceFileResponse(
                    requested_path=bundle.paths.policy.requested_path.as_posix(),
                    resolved_path=bundle.paths.policy.resolved_path.as_posix(),
                    used_example_fallback=bundle.paths.policy.used_example_fallback,
                    from_environment=bundle.paths.policy.from_environment,
                ),
                "workers": ConfigSourceFileResponse(
                    requested_path=bundle.paths.workers.requested_path.as_posix(),
                    resolved_path=bundle.paths.workers.resolved_path.as_posix(),
                    used_example_fallback=bundle.paths.workers.used_example_fallback,
                    from_environment=bundle.paths.workers.from_environment,
                ),
            },
        )

    @staticmethod
    def age_seconds(value: datetime | None, now: datetime) -> int | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(0, int((now - value).total_seconds()))
