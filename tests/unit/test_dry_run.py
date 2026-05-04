from __future__ import annotations

from pathlib import Path

from encodr_core.config import load_config_bundle
from encodr_core.planning import build_processing_plan
from encodr_core.planning.dry_run import build_dry_run_analysis_payload
from encodr_core.probe import parse_ffprobe_json_output

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ffprobe"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dry_run_payload_exposes_kept_and_removed_stream_decisions() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    media = parse_fixture("non4k_remux_languages.json")
    plan = build_processing_plan(
        media,
        bundle,
        source_path="/media/Movies/Example Remux Film (2024).mkv",
    )

    payload = build_dry_run_analysis_payload(media, plan)

    audio_decisions = payload["audio_stream_decisions"]
    assert audio_decisions[0] == {
        "index": 1,
        "language": "eng",
        "codec": "eac3",
        "channels": 6,
        "channel_layout": "5.1(side)",
        "title": "English 5.1",
        "default": True,
        "commentary": False,
        "selected": True,
        "role": "primary",
        "reason": "primary_preferred_audio",
    }
    assert next(item for item in audio_decisions if item["index"] == 2)["reason"] == "commentary_audio_removed"
    assert next(item for item in audio_decisions if item["index"] == 3)["reason"] == "non_preferred_audio_removed"

    subtitle_decisions = payload["subtitle_stream_decisions"]
    assert next(item for item in subtitle_decisions if item["index"] == 5) == {
        "index": 5,
        "language": "eng",
        "codec": "subrip",
        "title": "English Forced",
        "default": False,
        "forced": True,
        "hearing_impaired": False,
        "selected": True,
        "role": "forced",
        "reason": "forced_subtitle_preserved",
    }
    assert next(item for item in subtitle_decisions if item["index"] == 6)["reason"] == "non_preferred_subtitle_removed"


def parse_fixture(name: str):
    return parse_ffprobe_json_output((FIXTURES_DIR / name).read_text(encoding="utf-8"), file_path=FIXTURES_DIR / name)
