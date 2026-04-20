from __future__ import annotations

from pathlib import Path

from encodr_core.config import load_config_bundle
from encodr_core.planning import PlanAction, build_processing_plan
from encodr_core.probe import parse_ffprobe_json_output

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ffprobe"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_compliant_non_4k_file_results_in_skip() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("tv_episode.json")

    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/TV/Example Show/Season 01/Example Show - s01e01 - Pilot.mkv",
    )

    assert plan.action == PlanAction.SKIP
    assert plan.is_already_compliant is True
    assert plan.policy_context.selected_profile_name == "tv-default"


def test_non_4k_file_with_extra_languages_only_results_in_remux() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("non4k_remux_languages.json")

    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/Movies/Example Remux Film (2024).mkv",
    )

    assert plan.action == PlanAction.REMUX
    assert plan.video.preserve_original is True
    assert 3 in plan.audio.dropped_stream_indices
    assert 6 in plan.subtitles.dropped_stream_indices


def test_non_4k_file_requiring_codec_change_results_in_transcode() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("film_1080p.json")

    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/Movies/Example Film (2024).mkv",
    )

    assert plan.action == PlanAction.TRANSCODE
    assert plan.video.transcode_required is True
    assert plan.video.target_codec == "hevc"


def test_4k_file_under_strip_only_policy_results_in_remux_with_preserved_video() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("film_4k_hdr_dv.json")

    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/Movies/Example UHD Film (2023).mkv",
    )

    assert plan.action == PlanAction.REMUX
    assert plan.video.preserve_original is True
    assert plan.should_treat_as_protected is True
    assert plan.policy_context.selected_profile_name == "movies-default"


def test_file_with_no_acceptable_english_audio_results_in_manual_review() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("no_english_audio.json")

    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/Movies/Example Foreign Audio Film.mkv",
    )

    assert plan.action == PlanAction.MANUAL_REVIEW
    assert plan.audio.missing_required_audio is True
    assert any(reason.code == "manual_review_missing_english_audio" for reason in plan.reasons)


def test_forced_english_subtitles_are_preserved_in_selection_intent() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("non4k_remux_languages.json")

    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/Movies/Example Remux Film (2024).mkv",
    )

    assert 5 in plan.subtitles.forced_stream_indices
    assert 5 in plan.subtitles.selected_stream_indices


def test_commentary_track_is_removed_from_audio_selection_intent() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("non4k_remux_languages.json")

    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/Movies/Example Remux Film (2024).mkv",
    )

    assert 2 in plan.audio.commentary_removed_stream_indices
    assert 2 not in plan.audio.selected_stream_indices


def test_path_based_profile_override_resolution_uses_longest_match() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    movie_media = parse_fixture("film_1080p.json")
    tv_media = parse_fixture("tv_episode.json")

    movie_plan = build_processing_plan(
        movie_media,
        bundle,
        source_path="/media/Movies/Example Film (2024).mkv",
    )
    tv_plan = build_processing_plan(
        tv_media,
        bundle,
        source_path="/media/TV/Example Show/Season 01/Example Show - s01e01 - Pilot.mkv",
    )

    assert movie_plan.policy_context.selected_profile_name == "movies-default"
    assert movie_plan.policy_context.matched_path_prefix == "/media/Movies"
    assert tv_plan.policy_context.selected_profile_name == "tv-default"
    assert tv_plan.policy_context.matched_path_prefix == "/media/TV"


def test_low_confidence_subtitle_metadata_results_in_manual_review() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("ambiguous_forced_subtitle.json")

    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/Movies/Example Ambiguous Forced Subtitle.mkv",
    )

    assert plan.action == PlanAction.MANUAL_REVIEW
    assert any(
        warning.code == "manual_review_low_confidence_subtitle_metadata"
        for warning in plan.warnings
    )


def parse_fixture(name: str):
    return parse_ffprobe_json_output((FIXTURES_DIR / name).read_text(encoding="utf-8"), file_path=FIXTURES_DIR / name)
