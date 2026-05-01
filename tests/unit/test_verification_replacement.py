from __future__ import annotations

import errno
import shutil
from pathlib import Path

from encodr_core.config import load_config_bundle
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan, build_processing_plan
from encodr_core.probe import parse_ffprobe_json_output
from encodr_core.replacement import ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationStatus

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ffprobe"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_keep_original_policy_places_new_file_alongside_original(tmp_path: Path) -> None:
    service = ReplacementService()
    source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
    staged_path = tmp_path / "scratch" / "output.mkv"
    source_path.parent.mkdir(parents=True)
    staged_path.parent.mkdir(parents=True)
    source_path.write_text("original", encoding="utf-8")
    staged_path.write_text("new", encoding="utf-8")

    plan = replace_plan("non4k_remux_languages.json", source_path)
    plan.replace.in_place = False

    result = service.place_verified_output(
        source_path=source_path,
        staged_output_path=staged_path,
        plan=plan,
    )

    final_path = source_path.with_name("Example Film (2024).encodr.mkv")
    assert result.status == ReplacementStatus.SUCCEEDED
    assert result.final_output_path == final_path
    assert source_path.read_text(encoding="utf-8") == "original"
    assert final_path.read_text(encoding="utf-8") == "new"
    assert staged_path.exists() is False


def test_replace_in_place_policy_swaps_file_safely(tmp_path: Path) -> None:
    service = ReplacementService()
    source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
    staged_path = tmp_path / "scratch" / "output.mkv"
    source_path.parent.mkdir(parents=True)
    staged_path.parent.mkdir(parents=True)
    source_path.write_text("original", encoding="utf-8")
    staged_path.write_text("new", encoding="utf-8")

    plan = replace_plan("non4k_remux_languages.json", source_path)

    result = service.place_verified_output(
        source_path=source_path,
        staged_output_path=staged_path,
        plan=plan,
    )

    backup_path = source_path.with_name("Example Film (2024).encodr-backup.mkv")
    assert result.status == ReplacementStatus.SUCCEEDED
    assert result.final_output_path == source_path
    assert result.original_backup_path == backup_path
    assert source_path.read_text(encoding="utf-8") == "new"
    assert backup_path.read_text(encoding="utf-8") == "original"


def test_delete_original_policy_only_removes_backup_after_success(tmp_path: Path) -> None:
    service = ReplacementService()
    source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
    staged_path = tmp_path / "scratch" / "output.mkv"
    source_path.parent.mkdir(parents=True)
    staged_path.parent.mkdir(parents=True)
    source_path.write_text("original", encoding="utf-8")
    staged_path.write_text("new", encoding="utf-8")

    plan = replace_plan("non4k_remux_languages.json", source_path)
    plan.replace.delete_replaced_source = True

    result = service.place_verified_output(
        source_path=source_path,
        staged_output_path=staged_path,
        plan=plan,
    )

    backup_path = source_path.with_name("Example Film (2024).encodr-backup.mkv")
    assert result.status == ReplacementStatus.SUCCEEDED
    assert result.deleted_original_source is True
    assert result.original_backup_path is None
    assert source_path.read_text(encoding="utf-8") == "new"
    assert backup_path.exists() is False


def test_destination_collision_without_overwrite_permission_fails_clearly(tmp_path: Path) -> None:
    service = ReplacementService()
    source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
    staged_path = tmp_path / "scratch" / "output.mkv"
    final_path = tmp_path / "Movies" / "Example Film (2024).encodr.mkv"
    source_path.parent.mkdir(parents=True)
    staged_path.parent.mkdir(parents=True)
    source_path.write_text("original", encoding="utf-8")
    staged_path.write_text("new", encoding="utf-8")
    final_path.write_text("collision", encoding="utf-8")

    plan = replace_plan("non4k_remux_languages.json", source_path)
    plan.replace.in_place = False

    result = service.place_verified_output(
        source_path=source_path,
        staged_output_path=staged_path,
        plan=plan,
    )

    assert result.status == ReplacementStatus.FAILED
    assert "destination file already exists" in (result.failure_message or "").lower()
    assert source_path.read_text(encoding="utf-8") == "original"
    assert staged_path.read_text(encoding="utf-8") == "new"


def test_replacement_failure_preserves_original(tmp_path: Path, monkeypatch) -> None:
    service = ReplacementService()
    source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
    staged_path = tmp_path / "scratch" / "output.mkv"
    source_path.parent.mkdir(parents=True)
    staged_path.parent.mkdir(parents=True)
    source_path.write_text("original", encoding="utf-8")
    staged_path.write_text("new", encoding="utf-8")

    plan = replace_plan("non4k_remux_languages.json", source_path)

    def fail_move(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError(errno.EACCES, "permission denied")

    monkeypatch.setattr(shutil, "move", fail_move)
    result = service.place_verified_output(
        source_path=source_path,
        staged_output_path=staged_path,
        plan=plan,
    )

    assert result.status == ReplacementStatus.FAILED
    assert result.details["operation"] == "move_verified_output_into_place"
    assert result.details["source_path"] == source_path.as_posix()
    assert result.details["staged_output_path"] == staged_path.as_posix()
    assert result.details["final_output_path"] == source_path.as_posix()
    assert result.details["original_backup_path"] == source_path.with_name("Example Film (2024).encodr-backup.mkv").as_posix()
    assert result.details["errno"] == errno.EACCES
    assert "NAS share" in result.details["permission_hint"]
    assert result.details["source_exists"] is False
    assert result.details["staged_output_exists"] is True
    assert result.details["backup_exists"] is True
    assert result.details["rollback_succeeded"] is True
    assert result.details["source_exists_after_rollback"] is True
    assert result.details["staged_output_exists_after_rollback"] is True
    assert result.details["backup_exists_after_rollback"] is False
    assert source_path.read_text(encoding="utf-8") == "original"
    assert staged_path.read_text(encoding="utf-8") == "new"


def test_source_backup_permission_failure_returns_context_without_mutating_files(tmp_path: Path, monkeypatch) -> None:
    service = ReplacementService()
    source_path = tmp_path / "Movies" / "Example Film (2024).mkv"
    staged_path = tmp_path / "scratch" / "output.mkv"
    source_path.parent.mkdir(parents=True)
    staged_path.parent.mkdir(parents=True)
    source_path.write_text("original", encoding="utf-8")
    staged_path.write_text("new", encoding="utf-8")
    plan = replace_plan("non4k_remux_languages.json", source_path)
    original_rename = Path.rename

    def fail_source_rename(self: Path, target: Path) -> Path:
        if self == source_path:
            raise PermissionError(errno.EACCES, "permission denied")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_source_rename)
    result = service.place_verified_output(source_path=source_path, staged_output_path=staged_path, plan=plan)

    assert result.status == ReplacementStatus.FAILED
    assert result.details["operation"] == "move_source_to_backup"
    assert result.details["errno"] == errno.EACCES
    assert source_path.read_text(encoding="utf-8") == "original"
    assert staged_path.read_text(encoding="utf-8") == "new"
    assert source_path.with_name("Example Film (2024).encodr-backup.mkv").exists() is False


def test_output_probe_mismatch_with_plan_fails_verification(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    source_media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Example Film (2024).mkv")
    source_media.file_path.parent.mkdir(parents=True, exist_ok=True)
    source_media.file_path.write_text("source", encoding="utf-8")
    plan = build_processing_plan(source_media, bundle, source_path=source_media.file_path.as_posix())

    output_path = tmp_path / "scratch" / "output.mkv"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("staged", encoding="utf-8")
    mismatched_output = media_at_path(parse_fixture("film_1080p.json"), output_path)
    verifier = OutputVerifier(probe_client=StaticProbeClient(mismatched_output))

    result = verifier.verify_output(
        staged_output_path=output_path,
        plan=plan,
        source_media=source_media,
    )

    assert result.status == VerificationStatus.FAILED
    assert any(failure.code == "video_intent_satisfied" for failure in result.failures)


def test_verified_remux_output_passes_basic_verification(tmp_path: Path) -> None:
    source_media = media_at_path(parse_fixture("non4k_remux_languages.json"), tmp_path / "Movies" / "Example Film (2024).mkv")
    source_media.file_path.parent.mkdir(parents=True)
    source_media.file_path.write_text("source", encoding="utf-8")

    output_path = tmp_path / "scratch" / "output.mkv"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("staged", encoding="utf-8")
    output_media = media_at_path(parse_fixture("non4k_remux_languages.json"), output_path)
    verifier = OutputVerifier(probe_client=StaticProbeClient(output_media))

    plan = replace_plan("non4k_remux_languages.json", source_media.file_path)
    result = verifier.verify_output(
        staged_output_path=output_path,
        plan=plan,
        source_media=source_media,
    )

    assert result.status == VerificationStatus.PASSED
    assert result.output_summary is not None
    assert result.output_summary.audio_stream_count >= 1


def test_language_aware_audio_verification_uses_plan_intent(tmp_path: Path) -> None:
    source_media = media_at_path(parse_fixture("no_english_audio.json"), tmp_path / "Movies" / "Example Japanese Film.mkv")
    source_media.file_path.parent.mkdir(parents=True)
    source_media.file_path.write_text("source", encoding="utf-8")
    output_path = tmp_path / "scratch" / "output.mkv"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("staged", encoding="utf-8")
    output_media = media_at_path(parse_fixture("no_english_audio.json"), output_path)
    plan = replace_plan("no_english_audio.json", source_media.file_path)
    plan.audio = plan.audio.model_copy(update={"selected_stream_indices": [1], "required_language_codes": ["jpn"]})

    result = OutputVerifier(probe_client=StaticProbeClient(output_media)).verify_output(
        staged_output_path=output_path,
        plan=plan,
        source_media=source_media,
    )

    assert result.status == VerificationStatus.PASSED


def test_language_aware_audio_verification_fails_when_required_language_missing(tmp_path: Path) -> None:
    source_media = media_at_path(parse_fixture("non4k_remux_languages.json"), tmp_path / "Movies" / "Example German Film.mkv")
    source_media.file_path.parent.mkdir(parents=True)
    source_media.file_path.write_text("source", encoding="utf-8")
    output_path = tmp_path / "scratch" / "output.mkv"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("staged", encoding="utf-8")
    output_media = media_at_path(parse_fixture("non4k_remux_languages.json"), output_path)
    plan = replace_plan("non4k_remux_languages.json", source_media.file_path)
    plan.audio = plan.audio.model_copy(update={"selected_stream_indices": [1], "required_language_codes": ["deu"]})

    result = OutputVerifier(probe_client=StaticProbeClient(output_media)).verify_output(
        staged_output_path=output_path,
        plan=plan,
        source_media=source_media,
    )

    assert result.status == VerificationStatus.FAILED
    assert any(failure.code == "required_audio_present" for failure in result.failures)


def test_language_aware_subtitle_verification_uses_forced_language_intent(tmp_path: Path) -> None:
    source_media = media_at_path(parse_fixture("non4k_remux_languages.json"), tmp_path / "Movies" / "Example Film.mkv")
    source_media.file_path.parent.mkdir(parents=True)
    source_media.file_path.write_text("source", encoding="utf-8")
    output_path = tmp_path / "scratch" / "output.mkv"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("staged", encoding="utf-8")
    output_media = media_at_path(parse_fixture("non4k_remux_languages.json"), output_path)
    output_media.subtitle_streams[0].tags.language = "deu"
    output_media.subtitle_streams[0].disposition.forced = True
    plan = replace_plan("non4k_remux_languages.json", source_media.file_path)
    plan.subtitles = plan.subtitles.model_copy(
        update={
            "selected_stream_indices": [5],
            "forced_stream_indices": [5],
            "required_language_codes": ["deu"],
            "required_forced_language_codes": ["deu"],
        }
    )

    result = OutputVerifier(probe_client=StaticProbeClient(output_media)).verify_output(
        staged_output_path=output_path,
        plan=plan,
        source_media=source_media,
    )

    assert result.status == VerificationStatus.PASSED


def replace_plan(fixture_name: str, source_path: Path) -> ProcessingPlan:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = media_at_path(parse_fixture(fixture_name), source_path)
    return build_processing_plan(media, bundle, source_path=source_path.as_posix())


def parse_fixture(name: str) -> MediaFile:
    return parse_ffprobe_json_output((FIXTURES_DIR / name).read_text(encoding="utf-8"), file_path=FIXTURES_DIR / name)


def media_at_path(media: MediaFile, file_path: Path) -> MediaFile:
    updated = media.model_copy(deep=True)
    updated.container.file_path = file_path
    updated.container.file_name = file_path.name
    updated.container.extension = file_path.suffix.lower().lstrip(".")
    return updated


class StaticProbeClient:
    def __init__(self, media: MediaFile) -> None:
        self.media = media

    def probe_file(self, file_path):  # type: ignore[no-untyped-def]
        output_media = self.media.model_copy(deep=True)
        output_media.container.file_path = Path(file_path)
        output_media.container.file_name = Path(file_path).name
        output_media.container.extension = Path(file_path).suffix.lower().lstrip(".")
        return output_media
