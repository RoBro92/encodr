from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from encodr_core.media import StreamType, SubtitleKind
from encodr_core.probe import (
    FFprobeClient,
    ProbeBinaryNotFoundError,
    ProbeDataError,
    ProbeInvalidJsonError,
    ProbeProcessError,
    parse_ffprobe_json_output,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ffprobe"


def test_parses_normal_1080p_film_fixture() -> None:
    media = parse_fixture("film_1080p.json")

    assert media.file_name == "Example Film (2024).mkv"
    assert media.extension == "mkv"
    assert media.container.stream_count == 4
    assert media.container.duration_seconds == pytest.approx(7200.123)
    assert media.is_4k is False
    assert media.is_hdr_candidate is False
    assert len(media.video_streams) == 1
    assert len(media.audio_streams) == 1
    assert len(media.subtitle_streams) == 2
    assert len(media.chapters) == 2
    assert media.video_streams[0].frame_rate == pytest.approx(23.976, rel=1e-3)
    assert media.audio_streams[0].is_surround_candidate is True


def test_parses_tv_episode_fixture() -> None:
    media = parse_fixture("tv_episode.json")

    assert media.file_name == "Example Show - s01e01 - Pilot.mkv"
    assert media.has_english_audio is True
    assert media.has_surround_audio is False
    assert len(media.data_streams) == 1
    assert media.subtitle_streams[0].is_hearing_impaired_candidate is True
    assert media.subtitle_streams[0].subtitle_kind == SubtitleKind.TEXT


def test_parses_4k_hdr_dv_fixture() -> None:
    media = parse_fixture("film_4k_hdr_dv.json")

    assert media.is_4k is True
    assert media.is_hdr_candidate is True
    assert media.has_atmos_capable_audio is True
    assert media.has_forced_english_subtitle is True
    assert len(media.attachment_streams) == 1

    video = media.video_streams[0]
    assert video.is_4k is True
    assert video.dynamic_range.is_hdr_candidate is True
    assert video.dynamic_range.is_dolby_vision_candidate is True
    assert video.dynamic_range.hdr_format == "dolby_vision"
    assert "DOVI configuration record" in video.dynamic_range.side_data_types


def test_parses_multiple_audio_and_subtitle_languages() -> None:
    media = parse_fixture("multi_language.json")

    languages = [stream.language for stream in media.audio_streams]
    subtitle_languages = [stream.language for stream in media.subtitle_streams]

    assert languages == ["eng", "jpn", "eng"]
    assert subtitle_languages == ["eng", "eng", "fra"]
    assert media.has_english_audio is True
    assert media.has_forced_english_subtitle is True
    assert media.audio_streams[2].is_commentary_candidate is True


def test_forced_subtitle_detection_is_exposed_cleanly() -> None:
    media = parse_fixture("multi_language.json")

    forced = [stream for stream in media.subtitle_streams if stream.is_forced]
    assert len(forced) == 1
    assert forced[0].language == "eng"
    assert forced[0].title == "English Forced"


def test_surround_and_atmos_capable_audio_metadata_is_captured() -> None:
    media = parse_fixture("film_4k_hdr_dv.json")

    atmos_track = media.audio_streams[0]
    fallback_track = media.audio_streams[1]

    assert atmos_track.channels == 8
    assert atmos_track.channel_layout == "7.1"
    assert atmos_track.is_surround_candidate is True
    assert atmos_track.is_atmos_capable is True
    assert fallback_track.is_surround_candidate is True
    assert fallback_track.is_atmos_capable is False


def test_malformed_ffprobe_json_raises_structured_error() -> None:
    with pytest.raises(ProbeInvalidJsonError) as exc_info:
        parse_ffprobe_json_output("{not valid json", file_path="/tmp/bad.mkv")

    error = exc_info.value
    assert error.kind == "probe_invalid_json"
    assert error.file_path == Path("/tmp/bad.mkv")
    assert error.details


def test_missing_streams_in_probe_payload_raises_data_error() -> None:
    payload = json.dumps({"format": {"filename": "/tmp/example.mkv"}})

    with pytest.raises(ProbeDataError) as exc_info:
        parse_ffprobe_json_output(payload, file_path="/tmp/example.mkv")

    assert exc_info.value.kind == "probe_data_invalid"


def test_ffprobe_process_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr="Invalid data found when processing input",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    client = FFprobeClient(binary_path="/usr/bin/ffprobe")
    with pytest.raises(ProbeProcessError) as exc_info:
        client.probe_file("/tmp/failure.mkv")

    error = exc_info.value
    assert error.kind == "probe_process_failed"
    assert error.exit_code == 1
    assert "Invalid data" in (error.stderr or "")


def test_missing_ffprobe_binary_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("ffprobe not installed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    client = FFprobeClient(binary_path="/missing/ffprobe")
    with pytest.raises(ProbeBinaryNotFoundError) as exc_info:
        client.probe_file("/tmp/example.mkv")

    assert exc_info.value.kind == "probe_binary_missing"
    assert exc_info.value.binary_path == Path("/missing/ffprobe")


def parse_fixture(name: str):
    return parse_ffprobe_json_output((FIXTURES_DIR / name).read_text(encoding="utf-8"), file_path=FIXTURES_DIR / name)
