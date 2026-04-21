from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.files import FilesService
from app.services.setup import SetupStateService
from encodr_core.config import ConfigBundle
from encodr_core.config.base import FourKMode, OutputContainer, VideoCodec, deduplicate_preserving_order
from encodr_core.media.models import MediaFile
from encodr_core.config.profiles import ProfileConfig
from encodr_core.planning import build_processing_plan
from encodr_db.models import PlanSnapshot, ProbeSnapshot, TrackedFile
from encodr_db.repositories import PlanSnapshotRepository, TrackedFileRepository


class PlansService:
    def __init__(self, *, config_bundle: ConfigBundle, files_service: FilesService) -> None:
        self.config_bundle = config_bundle
        self.files_service = files_service

    def plan_file(
        self,
        session: Session,
        *,
        source_path: str,
    ) -> tuple[TrackedFile, ProbeSnapshot, PlanSnapshot]:
        tracked_file, probe_snapshot = self.files_service.probe_file(session, source_path=source_path)
        media_file = MediaFile.model_validate(probe_snapshot.payload)
        plan = build_processing_plan(
            media_file,
            self._config_bundle_for_source(source_path=tracked_file.source_path, media_file=media_file),
            source_path=tracked_file.source_path,
        )
        plan_snapshot = PlanSnapshotRepository(session).add_plan_snapshot(
            tracked_file,
            probe_snapshot,
            plan,
        )
        TrackedFileRepository(session).update_file_state_from_plan_result(tracked_file, plan)
        return tracked_file, probe_snapshot, plan_snapshot

    def dry_run_file(self, *, source_path: str):
        media_file = self.files_service.probe_source_file(source_path)
        plan = build_processing_plan(
            media_file,
            self._config_bundle_for_source(source_path=source_path, media_file=media_file),
            source_path=Path(source_path).resolve().as_posix(),
        )
        return media_file, plan

    def _config_bundle_for_source(self, *, source_path: str, media_file: MediaFile) -> ConfigBundle:
        setup_service = SetupStateService(config_bundle=self.config_bundle)
        ruleset = setup_service.ruleset_for_source(source_path)
        rules = setup_service.rules_for_source(source_path)
        if ruleset is None or rules is None:
            return self.config_bundle

        policy = self.config_bundle.policy
        audio_languages = ["eng"] if rules["keep_english_audio_only"] else self._all_languages(
            [stream.language for stream in media_file.audio_streams]
        )
        subtitle_languages = (
            ["eng"]
            if rules["keep_one_full_english_subtitle"]
            else self._all_languages([stream.language for stream in media_file.subtitle_streams], fallback=["und"])
        )
        forced_languages = (
            self._all_languages([stream.language for stream in media_file.subtitle_streams], fallback=["eng"])
            if rules["keep_forced_subtitles"]
            else ["und"]
        )
        next_policy = policy.model_copy(
            update={
                "audio": policy.audio.model_copy(
                    update={
                        "keep_languages": audio_languages,
                        "preserve_best_surround": rules["preserve_surround"],
                        "preserve_atmos_capable": rules["preserve_atmos"],
                    }
                ),
                "subtitles": policy.subtitles.model_copy(
                    update={
                        "keep_languages": subtitle_languages,
                        "keep_forced_languages": forced_languages,
                    }
                ),
                "languages": policy.languages.model_copy(
                    update={
                        "preserve_forced_subtitles": rules["keep_forced_subtitles"],
                    }
                ),
                "video": policy.video.model_copy(
                    update={
                        "output_container": OutputContainer(rules["output_container"]),
                        "non_4k": policy.video.non_4k.model_copy(
                            update={"preferred_codec": VideoCodec(rules["target_video_codec"])}
                        ),
                        "four_k": policy.video.four_k.model_copy(
                            update={"mode": FourKMode(rules["four_k_mode"])}
                        ),
                    }
                ),
            }
        )
        profiles = self.config_bundle.profiles
        profile_name = setup_service.profile_name_for_ruleset(ruleset)
        if profile_name and profile_name in profiles:
            current_profile = profiles[profile_name]
            profiles = {
                **profiles,
                profile_name: self._profile_with_rules(current_profile, rules),
            }
        return replace(self.config_bundle, policy=next_policy, profiles=profiles)

    @staticmethod
    def _all_languages(values: list[str | None], *, fallback: list[str] | None = None) -> list[str]:
        cleaned = deduplicate_preserving_order([value for value in values if value])
        if cleaned:
            return cleaned
        return fallback or ["eng"]

    def _profile_with_rules(self, profile: ProfileConfig, rules: dict[str, object]) -> ProfileConfig:
        update = {}
        if profile.audio is not None:
            update["audio"] = profile.audio.model_copy(
                update={
                    "keep_languages": ["eng"] if rules["keep_english_audio_only"] else None,
                    "preserve_best_surround": rules["preserve_surround"],
                    "preserve_atmos_capable": rules["preserve_atmos"],
                }
            )
        if profile.subtitles is not None:
            update["subtitles"] = profile.subtitles.model_copy(
                update={
                    "keep_languages": ["eng"] if rules["keep_one_full_english_subtitle"] else ["und"],
                    "keep_forced_languages": ["eng"] if rules["keep_forced_subtitles"] else ["und"],
                }
            )
        if profile.video is not None:
            next_video = profile.video.model_copy(update={"output_container": OutputContainer(rules["output_container"])})
            if next_video.non_4k is None:
                next_video = next_video.model_copy(
                    update={"non_4k": {"preferred_codec": VideoCodec(rules["target_video_codec"])}}
                )
            else:
                next_video = next_video.model_copy(
                    update={
                        "non_4k": next_video.non_4k.model_copy(
                            update={"preferred_codec": VideoCodec(rules["target_video_codec"])}
                        )
                    }
                )
            if next_video.four_k is None:
                next_video = next_video.model_copy(
                    update={"four_k": {"mode": FourKMode(rules["four_k_mode"])}}
                )
            else:
                next_video = next_video.model_copy(
                    update={
                        "four_k": next_video.four_k.model_copy(
                            update={"mode": FourKMode(rules["four_k_mode"])}
                        )
                    }
                )
            update["video"] = next_video
        return profile.model_copy(update=update)
