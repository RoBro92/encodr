from __future__ import annotations

from pathlib import Path

from encodr_core.config import load_config_bundle

from tests.helpers.api import import_api_module

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ruleset_resolution_uses_the_most_specific_matching_root(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)

    with import_api_module("app.services.setup") as setup_module:
        service = setup_module.SetupStateService(config_bundle=bundle)

    service.state_path = tmp_path / "setup-state.json"
    service._write_state_payload(  # type: ignore[attr-defined]
        {
            "movies_root": "/media",
            "tv_root": "/media/TV",
            "processing_rules": {
                "movies": None,
                "tv": None,
            },
        }
    )

    assert service.ruleset_for_source("/media/TV/Example Show/Season 01/Episode 01.mkv") == "tv"
