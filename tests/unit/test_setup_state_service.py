from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_execution_preferences_coerce_runtime_aliases(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)

    with import_api_module("app.services.setup") as setup_module:
        service = setup_module.SetupStateService(config_bundle=bundle)

    service.state_path = tmp_path / "setup-state.json"
    service.state_path.write_text(
        """
        {
          "execution_preferences": {
            "preferred_backend": "cpu",
            "allow_cpu_fallback": false
          }
        }
        """,
        encoding="utf-8",
    )

    assert service.get_execution_preferences() == {
        "preferred_backend": "cpu_only",
        "allow_cpu_fallback": False,
    }


def test_corrupt_setup_state_is_reported_backed_up_and_reset(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)

    with import_api_module("app.services.setup") as setup_module:
        service = setup_module.SetupStateService(config_bundle=bundle)

    service.state_path = tmp_path / "setup-state.json"
    service.state_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(setup_module.ApiValidationError) as error:
        service.get_state()

    assert "corrupt" in str(error.value).lower()
    assert "defaults were restored" in str(error.value)
    backups = list(tmp_path.glob("setup-state.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not-json"
    restored_payload = json.loads(service.state_path.read_text(encoding="utf-8"))
    assert restored_payload == service._empty_payload()  # type: ignore[attr-defined]
    assert service.get_state() == {"movies_root": None, "tv_root": None}


def test_setup_state_write_uses_atomic_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)

    with import_api_module("app.services.setup") as setup_module:
        service = setup_module.SetupStateService(config_bundle=bundle)

    service.state_path = tmp_path / "setup-state.json"

    def fail_direct_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("setup state writes must use atomic replacement")

    monkeypatch.setattr(Path, "write_text", fail_direct_write)

    service.update_execution_preferences(
        preferred_backend="prefer_intel_igpu",
        allow_cpu_fallback=False,
    )

    assert service.get_execution_preferences() == {
        "preferred_backend": "prefer_intel_igpu",
        "allow_cpu_fallback": False,
    }
    assert list(tmp_path.glob(".setup-state.json.*.tmp")) == []


def test_processing_rules_quality_preset_persists_with_values(tmp_path: Path) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)

    with import_api_module("app.services.setup") as setup_module:
        service = setup_module.SetupStateService(config_bundle=bundle)

    service.state_path = tmp_path / "setup-state.json"

    current = dict(service.get_processing_rules()["movies"]["current"])
    current.update(
        {
            "quality_preset": "custom",
            "target_quality_mode": "balanced",
            "target_crf": 24,
            "max_allowed_video_reduction_percent": 72,
        }
    )

    updated = service.update_processing_rules(
        movies=current,
        movies_4k=None,
        tv=None,
        tv_4k=None,
    )

    assert updated["movies"]["current"]["quality_preset"] == "custom"
    assert updated["movies"]["current"]["target_quality_mode"] == "balanced"
    assert updated["movies"]["current"]["target_crf"] == 24
    assert updated["movies"]["current"]["max_allowed_video_reduction_percent"] == 72
    assert service.rules_for_ruleset("movies")["quality_preset"] == "custom"
