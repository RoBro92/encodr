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
                "movies_4k": None,
                "tv": None,
                "tv_4k": None,
            },
        }
    )

    assert service.ruleset_for_source("/media/TV/Example Show/Season 01/Episode 01.mkv") == "tv"


def test_ruleset_resolution_selects_four_k_variant_when_requested(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)

    with import_api_module("app.services.setup") as setup_module:
        service = setup_module.SetupStateService(config_bundle=bundle)

    service.state_path = tmp_path / "setup-state.json"
    service._write_state_payload(  # type: ignore[attr-defined]
        {
            "movies_root": "/media/Movies",
            "tv_root": "/media/TV",
            "processing_rules": {
                "movies": None,
                "movies_4k": None,
                "tv": None,
                "tv_4k": None,
            },
        }
    )

    assert service.ruleset_for_source("/media/Movies/Example Film (2024).mkv", is_4k=True) == "movies_4k"
    assert service.ruleset_for_source("/media/TV/Example Show/Season 01/Episode 01.mkv", is_4k=True) == "tv_4k"


def test_execution_preferences_default_and_persist(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)

    with import_api_module("app.services.setup") as setup_module:
        service = setup_module.SetupStateService(config_bundle=bundle)

    service.state_path = tmp_path / "setup-state.json"

    defaults = service.get_execution_preferences()
    assert defaults == {
        "preferred_backend": "cpu_only",
        "allow_cpu_fallback": True,
    }

    updated = service.update_execution_preferences(
        preferred_backend="prefer_intel_igpu",
        allow_cpu_fallback=False,
    )

    assert updated == {
        "preferred_backend": "prefer_intel_igpu",
        "allow_cpu_fallback": False,
    }
    assert service.get_execution_preferences() == updated
