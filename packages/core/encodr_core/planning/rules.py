from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from encodr_core.config.base import OutputContainer
from encodr_core.config.bootstrap import ConfigBundle
from encodr_core.config.policy import (
    AudioRules,
    RenameTemplates,
    ReplacementRules,
    SubtitleRules,
    VideoRules,
)
from encodr_core.config.profiles import ProfileConfig, ProfileRenameConfig
from encodr_core.media.models import MediaFile
from encodr_core.planning.enums import RenameTemplateKind, RenameTemplateSource
from encodr_core.planning.models import PolicyContext, RenamePlan, ReplacePlan

EPISODE_PATTERN = re.compile(r"s\d{2}e\d{2}", re.IGNORECASE)


class ResolvedPlanningPolicy:
    def __init__(
        self,
        *,
        context: PolicyContext,
        audio_rules: AudioRules,
        subtitle_rules: SubtitleRules,
        video_rules: VideoRules,
        replacement_rules: ReplacementRules,
        renaming_rules: RenameTemplates,
        rename_override: ProfileRenameConfig | None,
    ) -> None:
        self.context = context
        self.audio_rules = audio_rules
        self.subtitle_rules = subtitle_rules
        self.video_rules = video_rules
        self.replacement_rules = replacement_rules
        self.renaming_rules = renaming_rules
        self.rename_override = rename_override


def resolve_planning_policy(
    media_file: MediaFile,
    config_bundle: ConfigBundle,
    *,
    source_path: Path | str | None = None,
) -> ResolvedPlanningPolicy:
    effective_source_path = Path(source_path) if source_path is not None else media_file.file_path
    selected_profile, matched_prefix = resolve_profile_for_path(
        config_bundle.policy.profiles.path_overrides,
        config_bundle,
        effective_source_path,
    )

    audio_rules = merge_optional_model(config_bundle.policy.audio, selected_profile.audio if selected_profile else None)
    subtitle_rules = merge_optional_model(
        config_bundle.policy.subtitles,
        selected_profile.subtitles if selected_profile else None,
    )
    video_rules = merge_video_rules(
        config_bundle.policy.video,
        selected_profile.video if selected_profile else None,
    )
    renaming_rules = config_bundle.policy.renaming

    context = PolicyContext(
        policy_name=config_bundle.policy.name,
        policy_version=config_bundle.policy.version,
        selected_profile_name=selected_profile.name if selected_profile else None,
        selected_profile_description=selected_profile.description if selected_profile else None,
        matched_path_prefix=matched_prefix,
        source_path=effective_source_path,
    )

    return ResolvedPlanningPolicy(
        context=context,
        audio_rules=audio_rules,
        subtitle_rules=subtitle_rules,
        video_rules=video_rules,
        replacement_rules=config_bundle.policy.replacement,
        renaming_rules=renaming_rules,
        rename_override=selected_profile.renaming if selected_profile else None,
    )


def resolve_profile_for_path(
    overrides: Sequence,
    config_bundle: ConfigBundle,
    source_path: Path,
) -> tuple[ProfileConfig | None, str | None]:
    source_text = source_path.as_posix()
    matches = [
        override
        for override in overrides
        if source_text.startswith(Path(override.path_prefix).as_posix())
    ]
    if not matches:
        return None, None

    matched_override = max(matches, key=lambda item: len(Path(item.path_prefix).as_posix()))
    return config_bundle.profiles[matched_override.profile], matched_override.path_prefix


def merge_optional_model(base_model, override_model):
    if override_model is None:
        return base_model
    return base_model.model_copy(update=override_model.model_dump(exclude_none=True))


def merge_video_rules(base_model: VideoRules, override_model) -> VideoRules:
    if override_model is None:
        return base_model

    update_values = override_model.model_dump(exclude_none=True, exclude={"non_4k", "four_k"})
    non_4k = base_model.non_4k
    four_k = base_model.four_k
    if override_model.non_4k is not None:
        non_4k = base_model.non_4k.model_copy(
            update=override_model.non_4k.model_dump(exclude_none=True)
        )
    if override_model.four_k is not None:
        four_k = base_model.four_k.model_copy(
            update=override_model.four_k.model_dump(exclude_none=True)
        )
    update_values.update({"non_4k": non_4k, "four_k": four_k})
    return base_model.model_copy(update=update_values)


def build_replace_plan(resolved_policy: ResolvedPlanningPolicy) -> ReplacePlan:
    rules = resolved_policy.replacement_rules
    return ReplacePlan(
        in_place=rules.in_place,
        require_verification=rules.require_verification,
        keep_original_until_verified=rules.keep_original_until_verified,
        delete_replaced_source=rules.delete_replaced_source,
    )


def build_rename_plan(resolved_policy: ResolvedPlanningPolicy, media_file: MediaFile) -> RenamePlan:
    renaming = resolved_policy.renaming_rules
    if not renaming.enabled:
        return RenamePlan(enabled=False)

    template_kind = infer_template_kind(
        resolved_policy.context.source_path,
        media_file,
        resolved_policy.context.selected_profile_name,
    )
    override = resolved_policy.rename_override

    if override is not None:
        if override.template:
            return RenamePlan(
                enabled=True,
                template_kind=template_kind,
                template_source=RenameTemplateSource.PROFILE,
                template_value=override.template,
            )
        if template_kind == RenameTemplateKind.EPISODE and override.episodes_template:
            return RenamePlan(
                enabled=True,
                template_kind=template_kind,
                template_source=RenameTemplateSource.PROFILE,
                template_value=override.episodes_template,
            )
        if template_kind == RenameTemplateKind.MOVIE and override.movies_template:
            return RenamePlan(
                enabled=True,
                template_kind=template_kind,
                template_source=RenameTemplateSource.PROFILE,
                template_value=override.movies_template,
            )

    template_value = renaming.movies_template
    if template_kind == RenameTemplateKind.EPISODE:
        template_value = renaming.episodes_template

    return RenamePlan(
        enabled=True,
        template_kind=template_kind,
        template_source=RenameTemplateSource.POLICY,
        template_value=template_value,
    )


def infer_template_kind(
    source_path: Path,
    media_file: MediaFile,
    selected_profile_name: str | None,
) -> RenameTemplateKind:
    source_text = source_path.as_posix().lower()
    file_name_text = media_file.file_name.lower()
    profile_text = (selected_profile_name or "").lower()

    if "tv" in source_text or "season" in source_text or "tv" in profile_text:
        return RenameTemplateKind.EPISODE
    if EPISODE_PATTERN.search(file_name_text):
        return RenameTemplateKind.EPISODE
    if "movie" in source_text or "movies" in source_text or "movie" in profile_text:
        return RenameTemplateKind.MOVIE
    return RenameTemplateKind.GENERIC


def target_container_extension(container: OutputContainer) -> str:
    return container.value

