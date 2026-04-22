from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.files import FilesService
from app.services.setup import SetupStateService
from encodr_core.config import ConfigBundle
from encodr_core.config.base import (
    FourKMode,
    OutputContainer,
    RuleHandlingMode,
    VideoCodec,
    VideoQualityMode,
    deduplicate_preserving_order,
)
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
        ruleset_override: str | None = None,
    ) -> tuple[TrackedFile, ProbeSnapshot, PlanSnapshot]:
        tracked_file, probe_snapshot = self.files_service.probe_file(session, source_path=source_path)
        media_file = MediaFile.model_validate(probe_snapshot.payload)
        plan = build_processing_plan(
            media_file,
            self._config_bundle_for_source(
                source_path=tracked_file.source_path,
                media_file=media_file,
                ruleset_override=ruleset_override,
            ),
            source_path=tracked_file.source_path,
        )
        plan_snapshot = PlanSnapshotRepository(session).add_plan_snapshot(
            tracked_file,
            probe_snapshot,
            plan,
        )
        TrackedFileRepository(session).update_file_state_from_plan_result(tracked_file, plan)
        return tracked_file, probe_snapshot, plan_snapshot

    def dry_run_file(self, *, source_path: str, ruleset_override: str | None = None):
        media_file = self.files_service.probe_source_file(source_path)
        plan = build_processing_plan(
            media_file,
            self._config_bundle_for_source(
                source_path=source_path,
                media_file=media_file,
                ruleset_override=ruleset_override,
            ),
            source_path=Path(source_path).resolve().as_posix(),
        )
        return media_file, plan

    def _config_bundle_for_source(
        self,
        *,
        source_path: str,
        media_file: MediaFile,
        ruleset_override: str | None = None,
    ) -> ConfigBundle:
        setup_service = SetupStateService(config_bundle=self.config_bundle)
        ruleset = ruleset_override or setup_service.ruleset_for_source(source_path, is_4k=media_file.is_4k)
        rules = (
            setup_service.rules_for_ruleset(ruleset) if ruleset is not None else None
        ) if ruleset_override else setup_service.rules_for_source(source_path, is_4k=media_file.is_4k)
        if ruleset is None or rules is None:
            return self.config_bundle

        policy = self.config_bundle.policy
        audio_languages = rules["preferred_audio_languages"]
        subtitle_languages = rules["preferred_subtitle_languages"]
        forced_languages = subtitle_languages if rules["keep_forced_subtitles"] else ["und"]
        handling_mode = RuleHandlingMode(rules["handling_mode"])
        quality_mode = VideoQualityMode(rules["target_quality_mode"])
        four_k_rules = policy.video.four_k.model_copy(
            update={
                "preferred_codec": VideoCodec(rules["target_video_codec"]),
                "quality_mode": quality_mode,
                "max_video_reduction_percent": rules["max_allowed_video_reduction_percent"],
            }
        )
        non_4k_rules = policy.video.non_4k.model_copy(
            update={
                "preferred_codec": VideoCodec(rules["target_video_codec"]),
                "quality_mode": quality_mode,
                "max_video_reduction_percent": rules["max_allowed_video_reduction_percent"],
            }
        )
        if media_file.is_4k:
            four_k_rules = four_k_rules.model_copy(
                update={
                    "mode": FourKMode.POLICY_CONTROLLED
                    if handling_mode == RuleHandlingMode.TRANSCODE
                    else FourKMode.STRIP_ONLY,
                    "allow_transcode": handling_mode == RuleHandlingMode.TRANSCODE,
                    "preserve_original_video": handling_mode != RuleHandlingMode.TRANSCODE,
                    "remove_non_english_audio": rules["keep_only_preferred_audio_languages"],
                    "remove_non_english_subtitles": rules["drop_other_subtitles"],
                }
            )
        else:
            non_4k_rules = non_4k_rules.model_copy(
                update={
                    "allow_transcode": handling_mode == RuleHandlingMode.TRANSCODE,
                    "decision_order": ["skip", "remux"]
                    if handling_mode != RuleHandlingMode.TRANSCODE
                    else ["skip", "remux", "transcode"],
                }
            )
        next_policy = policy.model_copy(
            update={
                "audio": policy.audio.model_copy(
                    update={
                        "keep_languages": audio_languages,
                        "keep_only_preferred_languages": rules["keep_only_preferred_audio_languages"],
                        "preserve_best_surround": rules["preserve_surround"],
                        "preserve_seven_one": rules["preserve_seven_one"],
                        "preserve_atmos_capable": rules["preserve_atmos"],
                    }
                ),
                "subtitles": policy.subtitles.model_copy(
                    update={
                        "keep_languages": subtitle_languages,
                        "keep_forced_languages": forced_languages,
                        "keep_one_full_preferred_subtitle": rules["keep_one_full_preferred_subtitle"],
                        "drop_other_subtitles": rules["drop_other_subtitles"],
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
                        "non_4k": non_4k_rules,
                        "four_k": four_k_rules,
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
                    "keep_languages": rules["preferred_audio_languages"],
                    "keep_only_preferred_languages": rules["keep_only_preferred_audio_languages"],
                    "preserve_best_surround": rules["preserve_surround"],
                    "preserve_seven_one": rules["preserve_seven_one"],
                    "preserve_atmos_capable": rules["preserve_atmos"],
                }
            )
        if profile.subtitles is not None:
            update["subtitles"] = profile.subtitles.model_copy(
                update={
                    "keep_languages": rules["preferred_subtitle_languages"],
                    "keep_forced_languages": rules["preferred_subtitle_languages"] if rules["keep_forced_subtitles"] else ["und"],
                    "keep_one_full_preferred_subtitle": rules["keep_one_full_preferred_subtitle"],
                    "drop_other_subtitles": rules["drop_other_subtitles"],
                }
            )
        if profile.video is not None:
            next_video = profile.video.model_copy(update={"output_container": OutputContainer(rules["output_container"])})
            if next_video.non_4k is None:
                next_video = next_video.model_copy(
                    update={
                        "non_4k": {
                            "preferred_codec": VideoCodec(rules["target_video_codec"]),
                            "quality_mode": VideoQualityMode(rules["target_quality_mode"]),
                            "max_video_reduction_percent": rules["max_allowed_video_reduction_percent"],
                        }
                    }
                )
            else:
                next_video = next_video.model_copy(
                    update={
                        "non_4k": next_video.non_4k.model_copy(
                            update={
                                "preferred_codec": VideoCodec(rules["target_video_codec"]),
                                "quality_mode": VideoQualityMode(rules["target_quality_mode"]),
                                "max_video_reduction_percent": rules["max_allowed_video_reduction_percent"],
                            }
                        )
                    }
                )
            if next_video.four_k is None:
                next_video = next_video.model_copy(
                    update={
                        "four_k": {
                            "preferred_codec": VideoCodec(rules["target_video_codec"]),
                            "mode": FourKMode.POLICY_CONTROLLED
                            if RuleHandlingMode(rules["handling_mode"]) == RuleHandlingMode.TRANSCODE
                            else FourKMode.STRIP_ONLY,
                            "allow_transcode": RuleHandlingMode(rules["handling_mode"]) == RuleHandlingMode.TRANSCODE,
                            "quality_mode": VideoQualityMode(rules["target_quality_mode"]),
                            "max_video_reduction_percent": rules["max_allowed_video_reduction_percent"],
                        }
                    }
                )
            else:
                next_video = next_video.model_copy(
                    update={
                        "four_k": next_video.four_k.model_copy(
                            update={
                                "preferred_codec": VideoCodec(rules["target_video_codec"]),
                                "mode": FourKMode.POLICY_CONTROLLED
                                if RuleHandlingMode(rules["handling_mode"]) == RuleHandlingMode.TRANSCODE
                                else FourKMode.STRIP_ONLY,
                                "allow_transcode": RuleHandlingMode(rules["handling_mode"]) == RuleHandlingMode.TRANSCODE,
                                "preserve_original_video": RuleHandlingMode(rules["handling_mode"]) != RuleHandlingMode.TRANSCODE,
                                "remove_non_english_audio": rules["keep_only_preferred_audio_languages"],
                                "remove_non_english_subtitles": rules["drop_other_subtitles"],
                                "quality_mode": VideoQualityMode(rules["target_quality_mode"]),
                                "max_video_reduction_percent": rules["max_allowed_video_reduction_percent"],
                            }
                        )
                    }
                )
            update["video"] = next_video
        return profile.model_copy(update=update)
