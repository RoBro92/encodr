from __future__ import annotations

from pathlib import Path

from encodr_core.config.base import FourKMode, OutputContainer, PolicyDecision
from encodr_core.config.bootstrap import ConfigBundle
from encodr_core.media.models import MediaFile, VideoStream
from encodr_core.planning.enums import (
    ConfidenceLevel,
    ContainerHandling,
    PlanAction,
    VideoHandling,
)
from encodr_core.planning.models import (
    ContainerPlan,
    PlanReason,
    PlanSummary,
    ProcessingPlan,
    SelectedStreamSet,
    VideoPlan,
)
from encodr_core.planning.reasons import make_reason
from encodr_core.planning.rules import (
    ResolvedPlanningPolicy,
    build_rename_plan,
    build_replace_plan,
    resolve_planning_policy,
    target_container_extension,
)
from encodr_core.planning.selection import select_audio_streams, select_subtitle_streams


def build_processing_plan(
    media_file: MediaFile,
    config_bundle: ConfigBundle,
    *,
    source_path: Path | str | None = None,
) -> ProcessingPlan:
    resolved_policy = resolve_planning_policy(media_file, config_bundle, source_path=source_path)
    reasons: list[PlanReason] = []
    warnings = []

    audio_result = select_audio_streams(
        media_file,
        resolved_policy.audio_rules,
        config_bundle.policy.languages,
    )
    subtitle_result = select_subtitle_streams(
        media_file,
        resolved_policy.subtitle_rules,
        config_bundle.policy.languages,
    )
    reasons.extend(audio_result.reasons)
    reasons.extend(subtitle_result.reasons)
    warnings.extend(audio_result.warnings)
    warnings.extend(subtitle_result.warnings)

    video_plan, video_reasons, requires_manual_review_for_video = build_video_plan(
        media_file,
        resolved_policy,
    )
    reasons.extend(video_reasons)

    container_plan = build_container_plan(media_file, resolved_policy.video_rules.output_container)
    rename_plan = build_rename_plan(resolved_policy, media_file)
    replace_plan = build_replace_plan(resolved_policy)

    selected_streams = SelectedStreamSet(
        video_stream_indices=[video_plan.primary_stream_index] if video_plan.primary_stream_index is not None else [],
        audio_stream_indices=audio_result.intent.selected_stream_indices,
        subtitle_stream_indices=subtitle_result.intent.selected_stream_indices,
        attachment_stream_indices=[stream.index for stream in media_file.attachment_streams],
        data_stream_indices=[stream.index for stream in media_file.data_streams],
        unknown_stream_indices=[stream.index for stream in media_file.unknown_streams],
    )

    should_treat_as_protected = (
        media_file.is_4k
        or media_file.is_hdr_candidate
        or media_file.has_atmos_capable_audio
    )

    audio_changes_needed = bool(audio_result.intent.dropped_stream_indices)
    subtitle_changes_needed = bool(subtitle_result.intent.dropped_stream_indices)
    stream_cleanup_needed = audio_changes_needed or subtitle_changes_needed
    compliance_candidate = (
        not video_plan.transcode_required
        and not stream_cleanup_needed
        and not container_plan.change_required
        and not warnings
        and not audio_result.intent.missing_required_audio
        and not subtitle_result.intent.ambiguous_forced_stream_indices
    )

    manual_review = (
        requires_manual_review_for_video
        or audio_result.requires_manual_review
        or subtitle_result.requires_manual_review
    )

    action = determine_action(
        media_file=media_file,
        resolved_policy=resolved_policy,
        video_plan=video_plan,
        compliance_candidate=compliance_candidate,
        stream_cleanup_needed=stream_cleanup_needed,
        container_change_needed=container_plan.change_required,
        manual_review_required=manual_review,
    )

    if action == PlanAction.SKIP:
        reasons.append(
            make_reason(
                "already_compliant",
                "The file already appears to comply with the effective policy.",
            )
        )

    confidence = determine_confidence(action, warnings)

    return ProcessingPlan(
        action=action,
        summary=PlanSummary(
            action=action,
            confidence=confidence,
            is_already_compliant=action == PlanAction.SKIP,
            should_treat_as_protected=should_treat_as_protected,
        ),
        policy_context=resolved_policy.context,
        selected_streams=selected_streams,
        audio=audio_result.intent,
        subtitles=subtitle_result.intent,
        video=video_plan,
        container=container_plan,
        rename=rename_plan,
        replace=replace_plan,
        reasons=reasons,
        warnings=warnings,
        confidence=confidence,
        is_already_compliant=action == PlanAction.SKIP,
        should_treat_as_protected=should_treat_as_protected,
    )


def build_video_plan(
    media_file: MediaFile,
    resolved_policy: ResolvedPlanningPolicy,
) -> tuple[VideoPlan, list[PlanReason], bool]:
    reasons: list[PlanReason] = []
    if len(media_file.video_streams) != 1:
        reasons.append(
            make_reason(
                "manual_review_video_stream_ambiguity",
                "The file does not expose exactly one video stream, so planning requires manual review.",
                stream_count=len(media_file.video_streams),
            )
        )
        return (
            VideoPlan(
                primary_stream_index=None,
                handling=VideoHandling.PRESERVE,
                preserve_original=True,
                target_codec=None,
                transcode_required=False,
                quality_mode=None,
                max_allowed_video_reduction_percent=None,
            ),
            reasons,
            True,
        )

    video_stream = media_file.video_streams[0]
    if media_file.is_4k:
        return build_4k_video_plan(video_stream, resolved_policy)
    return build_non_4k_video_plan(video_stream, resolved_policy)


def build_4k_video_plan(
    video_stream: VideoStream,
    resolved_policy: ResolvedPlanningPolicy,
) -> tuple[VideoPlan, list[PlanReason], bool]:
    rules = resolved_policy.video_rules.four_k
    target_codec = rules.preferred_codec.value
    transcode_required = False
    reasons: list[PlanReason] = []

    if rules.mode == FourKMode.STRIP_ONLY and not rules.allow_transcode:
        reasons.append(
            make_reason(
                "video_preserved_for_4k_policy",
                "4K video is preserved under the effective 4K policy.",
                stream_index=video_stream.index,
            )
        )
        return (
            VideoPlan(
                primary_stream_index=video_stream.index,
                handling=VideoHandling.PRESERVE,
                preserve_original=True,
                target_codec=video_stream.codec_name,
                transcode_required=False,
                quality_mode=rules.quality_mode.value,
                max_allowed_video_reduction_percent=rules.max_video_reduction_percent,
            ),
            reasons,
            False,
        )

    if not rules.allow_transcode:
        reasons.append(
            make_reason(
                "manual_review_unsupported_4k_policy_mode",
                "The effective 4K rule is not configured to allow video transcoding.",
                mode=rules.mode,
            )
        )
        return (
            VideoPlan(
                primary_stream_index=video_stream.index,
                handling=VideoHandling.PRESERVE,
                preserve_original=True,
                target_codec=video_stream.codec_name,
                transcode_required=False,
                quality_mode=rules.quality_mode.value,
                max_allowed_video_reduction_percent=rules.max_video_reduction_percent,
            ),
            reasons,
            True,
        )

    if video_stream.codec_name != target_codec:
        transcode_required = True
        reasons.append(
            make_reason(
                "video_transcode_required_for_4k_policy_codec",
                "4K video codec does not match the effective 4K policy target.",
                source_codec=video_stream.codec_name,
                target_codec=target_codec,
            )
        )

    if transcode_required:
        reasons.append(
            make_reason(
                "video_reduction_limit_applies",
                "Compression safety will be checked after encoding using video-only reduction.",
                max_allowed_video_reduction_percent=rules.max_video_reduction_percent,
            )
        )

    return (
        VideoPlan(
            primary_stream_index=video_stream.index,
            handling=VideoHandling.TRANSCODE_TO_POLICY if transcode_required else VideoHandling.PRESERVE,
            preserve_original=not transcode_required,
            target_codec=target_codec,
            transcode_required=transcode_required,
            quality_mode=rules.quality_mode.value,
            max_allowed_video_reduction_percent=rules.max_video_reduction_percent,
        ),
        reasons,
        False,
    )


def build_non_4k_video_plan(
    video_stream: VideoStream,
    resolved_policy: ResolvedPlanningPolicy,
) -> tuple[VideoPlan, list[PlanReason], bool]:
    rules = resolved_policy.video_rules.non_4k
    reasons: list[PlanReason] = []
    transcode_required = False
    target_codec = rules.preferred_codec.value

    if video_stream.codec_name != target_codec:
        transcode_required = True
        reasons.append(
            make_reason(
                "video_transcode_required_for_policy_codec",
                "Video codec does not match the effective non-4K policy target.",
                source_codec=video_stream.codec_name,
                target_codec=target_codec,
            )
        )

    max_bitrate = rules.max_video_bitrate_mbps * 1_000_000
    if video_stream.bit_rate is not None and video_stream.bit_rate > max_bitrate:
        transcode_required = True
        reasons.append(
            make_reason(
                "video_transcode_required_for_policy_bitrate",
                "Video bitrate exceeds the effective non-4K policy limit.",
                bit_rate=video_stream.bit_rate,
                max_bit_rate=max_bitrate,
            )
        )

    if video_stream.width is not None and video_stream.width > rules.max_width:
        transcode_required = True
        reasons.append(
            make_reason(
                "video_transcode_required_for_policy_width",
                "Video width exceeds the effective non-4K policy limit.",
                width=video_stream.width,
                max_width=rules.max_width,
            )
        )

    if transcode_required:
        reasons.append(
            make_reason(
                "video_reduction_limit_applies",
                "Compression safety will be checked after encoding using video-only reduction.",
                max_allowed_video_reduction_percent=rules.max_video_reduction_percent,
            )
        )

    return (
        VideoPlan(
            primary_stream_index=video_stream.index,
            handling=VideoHandling.TRANSCODE_TO_POLICY if transcode_required else VideoHandling.PRESERVE,
            preserve_original=not transcode_required,
            target_codec=target_codec,
            transcode_required=transcode_required,
            quality_mode=rules.quality_mode.value,
            max_allowed_video_reduction_percent=rules.max_video_reduction_percent,
        ),
        reasons,
        False,
    )


def build_container_plan(media_file: MediaFile, target_container: OutputContainer) -> ContainerPlan:
    source_extension = media_file.extension
    target_extension = target_container_extension(target_container)
    change_required = source_extension != target_extension
    return ContainerPlan(
        source_extension=source_extension,
        target_container=target_container,
        handling=ContainerHandling.REMUX_TO_TARGET if change_required else ContainerHandling.PRESERVE,
        change_required=change_required,
    )


def determine_action(
    *,
    media_file: MediaFile,
    resolved_policy: ResolvedPlanningPolicy,
    video_plan: VideoPlan,
    compliance_candidate: bool,
    stream_cleanup_needed: bool,
    container_change_needed: bool,
    manual_review_required: bool,
) -> PlanAction:
    if manual_review_required:
        return PlanAction.MANUAL_REVIEW

    if media_file.is_4k:
        if video_plan.transcode_required:
            if not resolved_policy.video_rules.four_k.allow_transcode:
                return PlanAction.MANUAL_REVIEW
            return PlanAction.TRANSCODE
        if compliance_candidate:
            return PlanAction.SKIP
        return PlanAction.REMUX

    if video_plan.transcode_required:
        if not resolved_policy.video_rules.non_4k.allow_transcode:
            return PlanAction.MANUAL_REVIEW
        if PolicyDecision.TRANSCODE not in resolved_policy.video_rules.non_4k.decision_order:
            return PlanAction.MANUAL_REVIEW
        return PlanAction.TRANSCODE

    if stream_cleanup_needed or container_change_needed:
        if PolicyDecision.REMUX not in resolved_policy.video_rules.non_4k.decision_order:
            return PlanAction.MANUAL_REVIEW
        return PlanAction.REMUX

    if compliance_candidate and PolicyDecision.SKIP in resolved_policy.video_rules.non_4k.decision_order:
        return PlanAction.SKIP

    return PlanAction.MANUAL_REVIEW


def determine_confidence(action: PlanAction, warnings) -> ConfidenceLevel:
    if action == PlanAction.MANUAL_REVIEW:
        return ConfidenceLevel.LOW
    if warnings:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.HIGH
