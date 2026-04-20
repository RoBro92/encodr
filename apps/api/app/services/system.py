from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from encodr_core.config import ConfigBundle
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


class SystemService:
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

    def path_status(self, path: Path | str) -> dict[str, object]:
        resolved = Path(path)
        return {
            "path": resolved.as_posix(),
            "exists": resolved.exists(),
            "is_directory": resolved.is_dir(),
            "readable": os.access(resolved, os.R_OK),
            "writable": os.access(resolved, os.W_OK),
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
