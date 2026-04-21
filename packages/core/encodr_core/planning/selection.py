from __future__ import annotations

from typing import Iterable

from encodr_core.config.policy import AudioRules, LanguagePreferences, SubtitleRules
from encodr_core.media.models import AudioStream, MediaFile, SubtitleStream
from encodr_core.planning.models import (
    AudioSelectionIntent,
    PlanReason,
    PlanWarning,
    SubtitleSelectionIntent,
)
from encodr_core.planning.reasons import make_reason, make_warning


class AudioSelectionResult:
    def __init__(
        self,
        intent: AudioSelectionIntent,
        reasons: list[PlanReason],
        warnings: list[PlanWarning],
        requires_manual_review: bool,
    ) -> None:
        self.intent = intent
        self.reasons = reasons
        self.warnings = warnings
        self.requires_manual_review = requires_manual_review


class SubtitleSelectionResult:
    def __init__(
        self,
        intent: SubtitleSelectionIntent,
        reasons: list[PlanReason],
        warnings: list[PlanWarning],
        requires_manual_review: bool,
    ) -> None:
        self.intent = intent
        self.reasons = reasons
        self.warnings = warnings
        self.requires_manual_review = requires_manual_review


def select_audio_streams(
    media_file: MediaFile,
    audio_rules: AudioRules,
    language_rules: LanguagePreferences,
) -> AudioSelectionResult:
    reasons: list[PlanReason] = []
    warnings: list[PlanWarning] = []
    preferred_languages = set(audio_rules.keep_languages)
    preferred_streams = [
        stream
        for stream in media_file.audio_streams
        if stream.language in preferred_languages or (stream.language is None and "und" in preferred_languages)
    ]
    candidate_streams = preferred_streams if audio_rules.keep_only_preferred_languages else list(media_file.audio_streams)
    commentary_removed = [
        stream.index
        for stream in candidate_streams
        if stream.is_commentary_candidate and not audio_rules.allow_commentary
    ]
    selectable_streams = [
        stream
        for stream in candidate_streams
        if audio_rules.allow_commentary or not stream.is_commentary_candidate
    ]

    if commentary_removed:
        reasons.append(
            make_reason(
                "commentary_audio_removed",
                "Commentary audio tracks are not selected under the active policy.",
                stream_indices=commentary_removed,
            )
        )

    if audio_rules.keep_only_preferred_languages and not preferred_streams:
        undetermined_present = any(stream.language is None for stream in media_file.audio_streams)
        if undetermined_present and not language_rules.drop_undetermined_audio:
            warnings.append(
                make_warning(
                    "undetermined_audio_present",
                    "Undetermined audio tracks are present but no preferred-language audio was found.",
                )
            )
        reasons.append(
            make_reason(
                "manual_review_missing_english_audio",
                "No acceptable preferred-language audio track was found.",
            )
        )
        return AudioSelectionResult(
            intent=AudioSelectionIntent(
                selected_stream_indices=[],
                dropped_stream_indices=[stream.index for stream in media_file.audio_streams],
                commentary_removed_stream_indices=commentary_removed,
                available_preferred_language_stream_indices=[stream.index for stream in preferred_streams],
                missing_required_audio=True,
            ),
            reasons=reasons,
            warnings=warnings,
            requires_manual_review=True,
        )

    if not selectable_streams:
        reasons.append(
            make_reason(
                "manual_review_no_usable_audio",
                "No acceptable audio track remained after applying the active audio rules.",
            )
        )
        return AudioSelectionResult(
            intent=AudioSelectionIntent(
                selected_stream_indices=[],
                dropped_stream_indices=[stream.index for stream in media_file.audio_streams],
                commentary_removed_stream_indices=commentary_removed,
                available_preferred_language_stream_indices=[stream.index for stream in preferred_streams],
                missing_required_audio=True,
            ),
            reasons=reasons,
            warnings=warnings,
            requires_manual_review=True,
        )

    sorted_streams = sorted(
        selectable_streams,
        key=lambda stream: audio_stream_score(stream, audio_rules, preferred_languages),
        reverse=True,
    )
    selected: list[AudioStream] = []

    if audio_rules.preserve_atmos_capable:
        for stream in sorted_streams:
            if stream.is_atmos_capable and stream not in selected:
                selected.append(stream)

    if audio_rules.preserve_seven_one:
        for stream in sorted_streams:
            if is_seven_one_candidate(stream) and stream not in selected:
                selected.append(stream)
                break

    if audio_rules.preserve_best_surround:
        for stream in sorted_streams:
            if stream.is_surround_candidate and stream not in selected:
                selected.append(stream)
                break

    for stream in sorted_streams:
        if stream not in selected:
            selected.append(stream)
        if len(selected) >= audio_rules.max_tracks_to_keep:
            break

    selected = selected[: audio_rules.max_tracks_to_keep]
    selected_indices = [stream.index for stream in selected]
    dropped_indices = [
        stream.index for stream in media_file.audio_streams if stream.index not in selected_indices
    ]

    non_preferred_removed = [
        stream.index
        for stream in media_file.audio_streams
        if stream.language not in preferred_languages and stream.index in dropped_indices
    ]
    if audio_rules.keep_only_preferred_languages and non_preferred_removed:
        reasons.append(
            make_reason(
                "non_preferred_audio_removed",
                "Non-preferred-language audio tracks are not selected.",
                stream_indices=non_preferred_removed,
            )
        )

    preserved_atmos = [stream.index for stream in selected if stream.is_atmos_capable]
    if preserved_atmos:
        reasons.append(
            make_reason(
                "atmos_audio_preserved",
                "Atmos-capable preferred-language audio is preserved.",
                stream_indices=preserved_atmos,
            )
        )

    preserved_surround = [stream.index for stream in selected if stream.is_surround_candidate]
    if preserved_surround:
        reasons.append(
            make_reason(
                "best_surround_audio_preserved",
                "Best available surround-capable preferred-language audio is preserved.",
                stream_indices=preserved_surround,
            )
        )

    if audio_rules.keep_only_preferred_languages and any(stream.language is None for stream in media_file.audio_streams):
        warnings.append(
            make_warning(
                "undetermined_audio_not_selected",
                "Some audio tracks do not declare a language and are not selected automatically.",
            )
        )

    intent = AudioSelectionIntent(
        selected_stream_indices=selected_indices,
        dropped_stream_indices=dropped_indices,
        primary_stream_index=selected[0].index if selected else None,
        preserved_atmos_stream_indices=preserved_atmos,
        preserved_surround_stream_indices=preserved_surround,
        commentary_removed_stream_indices=commentary_removed,
        available_preferred_language_stream_indices=[stream.index for stream in preferred_streams],
        missing_required_audio=False,
    )
    return AudioSelectionResult(intent=intent, reasons=reasons, warnings=warnings, requires_manual_review=False)


def select_subtitle_streams(
    media_file: MediaFile,
    subtitle_rules: SubtitleRules,
    language_rules: LanguagePreferences,
) -> SubtitleSelectionResult:
    reasons: list[PlanReason] = []
    warnings: list[PlanWarning] = []
    preferred_languages = set(subtitle_rules.keep_languages)
    forced_languages = set(subtitle_rules.keep_forced_languages)

    forced_candidates: list[SubtitleStream] = []
    ambiguous_forced: list[SubtitleStream] = []
    if language_rules.preserve_forced_subtitles:
        forced_candidates = [
            stream
            for stream in media_file.subtitle_streams
            if stream.language in forced_languages and stream.disposition.forced
        ]
        ambiguous_forced = [
            stream
            for stream in media_file.subtitle_streams
            if stream.language in forced_languages
            and not stream.disposition.forced
            and contains_forced_marker(stream)
        ]

    if ambiguous_forced and language_rules.preserve_forced_subtitles:
        warnings.append(
            make_warning(
                "manual_review_low_confidence_subtitle_metadata",
                "Forced subtitle intent looks ambiguous in metadata.",
                stream_indices=[stream.index for stream in ambiguous_forced],
            )
        )
        reasons.append(
            make_reason(
                "manual_review_low_confidence_subtitle_metadata",
                "Forced subtitle metadata is ambiguous and requires manual review.",
                stream_indices=[stream.index for stream in ambiguous_forced],
            )
        )

    main_candidates = [
        stream
        for stream in media_file.subtitle_streams
        if stream.language in preferred_languages
        and not stream.disposition.forced
        and not contains_forced_marker(stream)
        and not stream.is_hearing_impaired_candidate
    ]
    main_candidates = sorted(main_candidates, key=subtitle_stream_score, reverse=True)

    hearing_impaired_candidates = [
        stream
        for stream in media_file.subtitle_streams
        if stream.language in preferred_languages and stream.is_hearing_impaired_candidate
    ]
    hearing_impaired_candidates = sorted(
        hearing_impaired_candidates, key=subtitle_stream_score, reverse=True
    )

    selected: list[SubtitleStream] = []
    selected.extend(sorted(forced_candidates, key=subtitle_stream_score, reverse=True))

    main_stream: SubtitleStream | None = None
    if subtitle_rules.keep_one_full_preferred_subtitle and main_candidates:
        main_stream = main_candidates[0]
        if main_stream not in selected:
            selected.append(main_stream)

    hearing_impaired_streams: list[SubtitleStream] = []
    if subtitle_rules.keep_hearing_impaired and hearing_impaired_candidates:
        selected_sdh = hearing_impaired_candidates[0]
        hearing_impaired_streams.append(selected_sdh)
        if selected_sdh not in selected:
            selected.append(selected_sdh)

    if not subtitle_rules.drop_other_subtitles:
        selected = list(media_file.subtitle_streams)

    selected_indices = [stream.index for stream in selected]
    dropped_indices = [
        stream.index for stream in media_file.subtitle_streams if stream.index not in selected_indices
    ]
    removed_non_preferred = [
        stream.index
        for stream in media_file.subtitle_streams
        if stream.language not in preferred_languages and stream.index in dropped_indices
    ]
    if subtitle_rules.drop_other_subtitles and removed_non_preferred:
        reasons.append(
            make_reason(
                "non_preferred_subtitles_removed",
                "Non-preferred-language subtitle tracks are not selected.",
                stream_indices=removed_non_preferred,
            )
        )

    if forced_candidates:
        reasons.append(
            make_reason(
                "forced_english_subtitles_preserved",
                "Forced preferred-language subtitle tracks are preserved.",
                stream_indices=[stream.index for stream in forced_candidates],
            )
        )

    if not selected and media_file.subtitle_streams:
        warnings.append(
            make_warning(
                "english_subtitle_not_found",
                "No preferred-language subtitle tracks were selected.",
            )
        )

    intent = SubtitleSelectionIntent(
        selected_stream_indices=selected_indices,
        dropped_stream_indices=dropped_indices,
        forced_stream_indices=[stream.index for stream in forced_candidates],
        main_stream_index=main_stream.index if main_stream else None,
        hearing_impaired_stream_indices=[stream.index for stream in hearing_impaired_streams],
        ambiguous_forced_stream_indices=[stream.index for stream in ambiguous_forced],
    )
    return SubtitleSelectionResult(
        intent=intent,
        reasons=reasons,
        warnings=warnings,
        requires_manual_review=bool(ambiguous_forced),
    )


def audio_stream_score(
    stream: AudioStream,
    audio_rules: AudioRules,
    preferred_languages: set[str],
) -> tuple[int, int, int, int, int, int, int]:
    codec_preference = score_codec_preference(stream.codec_name, audio_rules.preferred_codecs)
    return (
        1 if stream.language in preferred_languages or (stream.language is None and "und" in preferred_languages) else 0,
        1 if stream.is_atmos_capable and audio_rules.preserve_atmos_capable else 0,
        1 if is_seven_one_candidate(stream) and audio_rules.preserve_seven_one else 0,
        1 if stream.is_surround_candidate and audio_rules.preserve_best_surround else 0,
        stream.channels or 0,
        codec_preference,
        1 if stream.disposition.default else 0,
        -stream.index,
    )


def score_codec_preference(codec_name: str | None, preferred_codecs: Iterable[str]) -> int:
    if codec_name is None:
        return 0
    lowered = codec_name.lower()
    ranked = [item.lower() for item in preferred_codecs]
    if lowered not in ranked:
        return 0
    return len(ranked) - ranked.index(lowered)


def subtitle_stream_score(stream: SubtitleStream) -> tuple[int, int, int]:
    return (
        1 if stream.disposition.default else 0,
        1 if stream.is_forced else 0,
        -stream.index,
    )


def contains_forced_marker(stream: SubtitleStream) -> bool:
    values = [stream.title or "", stream.tags.handler_name or "", *stream.tags.raw.values()]
    combined = " ".join(values).lower()
    return "forced" in combined


def is_seven_one_candidate(stream: AudioStream) -> bool:
    layout = (stream.channel_layout or "").lower()
    return (stream.channels or 0) >= 8 or "7.1" in layout
