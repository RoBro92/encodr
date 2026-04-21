from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

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
    deduplicate_preserving_order,
)


class LanguagePreferences(LanguageListModel):
    preferred_audio: list[LanguageCode] = Field(min_length=1)
    preferred_subtitles: list[LanguageCode] = Field(min_length=1)
    preserve_forced_subtitles: bool = True
    drop_undetermined_audio: bool = False
    drop_undetermined_subtitles: bool = True

    @field_validator("preferred_audio", "preferred_subtitles")
    @classmethod
    def deduplicate_languages(cls, value: list[str]) -> list[str]:
        return deduplicate_preserving_order(value)


class SubtitleRules(LanguageListModel):
    keep_languages: list[LanguageCode] = Field(min_length=1)
    keep_forced_languages: list[LanguageCode] = Field(min_length=1)
    keep_commentary: bool = False
    keep_hearing_impaired: bool = True
    keep_one_full_preferred_subtitle: bool = True
    drop_other_subtitles: bool = True

    @field_validator("keep_languages", "keep_forced_languages")
    @classmethod
    def deduplicate_languages(cls, value: list[str]) -> list[str]:
        return deduplicate_preserving_order(value)


class AudioRules(LanguageListModel):
    keep_languages: list[LanguageCode] = Field(min_length=1)
    keep_only_preferred_languages: bool = True
    preserve_best_surround: bool = True
    preserve_seven_one: bool = True
    preserve_atmos_capable: bool = True
    preferred_codecs: list[NonEmptyString] = Field(min_length=1)
    allow_commentary: bool = False
    max_tracks_to_keep: PositiveInt = 2

    @field_validator("keep_languages", "preferred_codecs")
    @classmethod
    def deduplicate_items(cls, value: list[str]) -> list[str]:
        return deduplicate_preserving_order(value)


class NonFourKVideoRules(ConfigModel):
    decision_order: list[PolicyDecision] = Field(min_length=1)
    preferred_codec: VideoCodec = VideoCodec.HEVC
    allow_transcode: bool = True
    quality_mode: VideoQualityMode = VideoQualityMode.HIGH_QUALITY
    max_video_reduction_percent: NonNegativeInt = 35
    max_video_bitrate_mbps: PositiveInt
    max_width: PositiveInt

    @field_validator("decision_order")
    @classmethod
    def unique_decisions(cls, value: list[str]) -> list[str]:
        deduplicated = deduplicate_preserving_order(value)
        if len(deduplicated) != len(value):
            raise ValueError("decision_order must not contain duplicate values.")
        return deduplicated

    @model_validator(mode="after")
    def validate_transcode_setting(self) -> "NonFourKVideoRules":
        if not self.allow_transcode and PolicyDecision.TRANSCODE in self.decision_order:
            raise ValueError(
                "decision_order cannot include 'transcode' when allow_transcode is false."
            )
        return self


class FourKVideoRules(ConfigModel):
    mode: FourKMode = FourKMode.STRIP_ONLY
    preferred_codec: VideoCodec = VideoCodec.HEVC
    preserve_original_video: bool = True
    preserve_original_audio: bool = True
    allow_transcode: bool = False
    quality_mode: VideoQualityMode = VideoQualityMode.HIGH_QUALITY
    max_video_reduction_percent: NonNegativeInt = 20
    remove_non_english_audio: bool = True
    remove_non_english_subtitles: bool = True

    @model_validator(mode="after")
    def validate_mode(self) -> "FourKVideoRules":
        if self.mode == FourKMode.STRIP_ONLY and self.allow_transcode:
            raise ValueError("strip_only mode cannot allow 4K transcoding.")
        return self


class VideoRules(ConfigModel):
    output_container: OutputContainer = OutputContainer.MKV
    non_4k: NonFourKVideoRules
    four_k: FourKVideoRules


class ReplacementRules(ConfigModel):
    in_place: bool = True
    require_verification: bool = True
    keep_original_until_verified: bool = True
    delete_replaced_source: bool = False

    @model_validator(mode="after")
    def validate_replacement_safety(self) -> "ReplacementRules":
        if self.delete_replaced_source and not self.require_verification:
            raise ValueError("delete_replaced_source requires verification to be enabled.")
        return self


class RenameTagRules(ConfigModel):
    include_resolution: bool = False
    include_video_codec: bool = False
    include_edition: bool = False


class RenameTemplates(ConfigModel):
    enabled: bool = True
    movies_template: NonEmptyString
    episodes_template: NonEmptyString
    sanitise_for_filesystem: bool = True
    tag_rules: RenameTagRules = Field(default_factory=RenameTagRules)


class PathProfileOverride(ConfigModel):
    path_prefix: NonEmptyString
    profile: NonEmptyString


class ProfileReferenceConfig(ConfigModel):
    path_overrides: list[PathProfileOverride] = Field(default_factory=list)

    @field_validator("path_overrides")
    @classmethod
    def unique_path_prefixes(cls, value: list[PathProfileOverride]) -> list[PathProfileOverride]:
        seen: set[str] = set()
        for item in value:
            if item.path_prefix in seen:
                raise ValueError(
                    f"path_overrides contains duplicate path_prefix '{item.path_prefix}'."
                )
            seen.add(item.path_prefix)
        return value


class PolicyConfig(ConfigModel):
    version: PositiveInt
    name: NonEmptyString
    description: NonEmptyString
    languages: LanguagePreferences
    subtitles: SubtitleRules
    audio: AudioRules
    video: VideoRules
    replacement: ReplacementRules
    renaming: RenameTemplates
    profiles: ProfileReferenceConfig = Field(default_factory=ProfileReferenceConfig)

    @field_validator("description", mode="before")
    @classmethod
    def coerce_description(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value
