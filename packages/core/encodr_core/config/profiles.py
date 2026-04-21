from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from pydantic import Field

from encodr_core.config.base import (
    ConfigModel,
    FourKMode,
    LanguageCode,
    LanguageListModel,
    NonNegativeInt,
    NonEmptyString,
    OutputContainer,
    PolicyDecision,
    PositiveInt,
    VideoCodec,
    VideoQualityMode,
)
from encodr_core.config.errors import ConfigError, ConfigErrorDetail
from encodr_core.config.policy import PolicyConfig


class ProfileSubtitleRules(LanguageListModel):
    keep_languages: list[LanguageCode] | None = None
    keep_forced_languages: list[LanguageCode] | None = None
    keep_commentary: bool | None = None
    keep_hearing_impaired: bool | None = None
    keep_one_full_preferred_subtitle: bool | None = None
    drop_other_subtitles: bool | None = None


class ProfileAudioRules(LanguageListModel):
    keep_languages: list[LanguageCode] | None = None
    keep_only_preferred_languages: bool | None = None
    preserve_best_surround: bool | None = None
    preserve_seven_one: bool | None = None
    preserve_atmos_capable: bool | None = None
    preferred_codecs: list[NonEmptyString] | None = None
    allow_commentary: bool | None = None
    max_tracks_to_keep: PositiveInt | None = None


class ProfileNonFourKVideoRules(ConfigModel):
    decision_order: list[PolicyDecision] | None = None
    preferred_codec: VideoCodec | None = None
    allow_transcode: bool | None = None
    quality_mode: VideoQualityMode | None = None
    max_video_reduction_percent: NonNegativeInt | None = None
    max_video_bitrate_mbps: PositiveInt | None = None
    max_width: PositiveInt | None = None


class ProfileFourKVideoRules(ConfigModel):
    mode: FourKMode | None = None
    preferred_codec: VideoCodec | None = None
    preserve_original_video: bool | None = None
    preserve_original_audio: bool | None = None
    allow_transcode: bool | None = None
    quality_mode: VideoQualityMode | None = None
    max_video_reduction_percent: NonNegativeInt | None = None
    remove_non_english_audio: bool | None = None
    remove_non_english_subtitles: bool | None = None


class ProfileVideoRules(ConfigModel):
    output_container: OutputContainer | None = None
    non_4k: ProfileNonFourKVideoRules | None = None
    four_k: ProfileFourKVideoRules | None = None


class ProfileRenameConfig(ConfigModel):
    template: NonEmptyString | None = None
    movies_template: NonEmptyString | None = None
    episodes_template: NonEmptyString | None = None


class ProfileConfig(ConfigModel):
    name: NonEmptyString
    description: NonEmptyString
    subtitles: ProfileSubtitleRules | None = None
    audio: ProfileAudioRules | None = None
    video: ProfileVideoRules | None = None
    renaming: ProfileRenameConfig | None = None


class ProfileConfigDocument(ConfigModel):
    profile: ProfileConfig


@dataclass(frozen=True, slots=True)
class LoadedProfiles:
    profiles: dict[str, ProfileConfig]
    sources: dict[str, Path]


def validate_policy_profile_references(
    policy: PolicyConfig,
    loaded_profiles: Mapping[str, ProfileConfig],
    *,
    source: Path | None,
) -> None:
    missing_details: list[ConfigErrorDetail] = []

    for index, override in enumerate(policy.profiles.path_overrides):
        if override.profile not in loaded_profiles:
            missing_details.append(
                ConfigErrorDetail(
                    location=f"profiles.path_overrides[{index}].profile",
                    message=f"Referenced profile '{override.profile}' does not exist.",
                    input_value=override.profile,
                )
            )

    if missing_details:
        raise ConfigError.invalid_reference(
            source,
            "Policy references profile names that are not defined in the profiles directory.",
            details=missing_details,
        )
