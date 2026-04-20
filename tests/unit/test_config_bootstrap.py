from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from encodr_core.config import (
    APP_CONFIG_PATH_ENV,
    POLICY_CONFIG_PATH_ENV,
    WORKERS_CONFIG_PATH_ENV,
    ConfigError,
    load_config_bundle,
    load_profiles_from_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_loads_example_config_bundle_from_repository_root() -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)

    assert bundle.app.name == "encodr"
    assert bundle.policy.name == "default-policy"
    assert bundle.workers.local.id == "worker-local"
    assert bundle.paths.app.used_example_fallback is True
    assert bundle.paths.policy.used_example_fallback is True
    assert bundle.paths.workers.used_example_fallback is True
    assert "movies-default" in bundle.profiles
    assert "tv-default" in bundle.profiles


def test_loads_non_example_config_files(tmp_path: Path) -> None:
    config_dir = copy_example_config_tree(tmp_path)
    materialise_primary_config_files(config_dir)

    bundle = load_config_bundle(project_root=tmp_path)

    assert bundle.paths.app.used_example_fallback is False
    assert bundle.paths.policy.used_example_fallback is False
    assert bundle.paths.workers.used_example_fallback is False
    assert bundle.policy.video.non_4k.preferred_codec == "hevc"


def test_missing_default_config_file_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_config_bundle(project_root=tmp_path)

    error = exc_info.value
    assert error.kind == "missing_file"
    assert error.source == (tmp_path / "config" / "app.yaml").resolve()


def test_malformed_yaml_raises_clear_error(tmp_path: Path) -> None:
    config_dir = copy_example_config_tree(tmp_path)
    materialise_primary_config_files(config_dir)
    write_file(config_dir / "app.yaml", "app:\n  name: broken\n  api: [\n")

    with pytest.raises(ConfigError) as exc_info:
        load_config_bundle(project_root=tmp_path)

    assert exc_info.value.kind == "malformed_yaml"


def test_missing_required_fields_raise_validation_error(tmp_path: Path) -> None:
    config_dir = copy_example_config_tree(tmp_path)
    materialise_primary_config_files(config_dir)
    write_file(
        config_dir / "policy.yaml",
        """
version: 1
description: Missing required fields.
languages:
  preferred_audio: [eng]
  preferred_subtitles: [eng]
  preserve_forced_subtitles: true
  drop_undetermined_audio: false
  drop_undetermined_subtitles: true
subtitles:
  keep_languages: [eng]
  keep_forced_languages: [eng]
  keep_commentary: false
  keep_hearing_impaired: true
audio:
  keep_languages: [eng]
  preserve_best_surround: true
  preserve_atmos_capable: true
  preferred_codecs: [truehd]
  allow_commentary: false
  max_tracks_to_keep: 2
video:
  output_container: mkv
  non_4k:
    decision_order: [skip, remux]
    preferred_codec: hevc
    allow_transcode: false
    max_video_bitrate_mbps: 12
    max_width: 1920
  four_k:
    mode: strip_only
    preserve_original_video: true
    preserve_original_audio: true
    allow_transcode: false
    remove_non_english_audio: true
    remove_non_english_subtitles: true
replacement:
  in_place: true
  require_verification: true
  keep_original_until_verified: true
  delete_replaced_source: false
renaming:
  enabled: true
  movies_template: "{{ title }}"
  episodes_template: "{{ series_title }}"
  sanitise_for_filesystem: true
""",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config_bundle(project_root=tmp_path)

    assert exc_info.value.kind == "validation_error"
    locations = {detail.location for detail in exc_info.value.details}
    assert "name" in locations


def test_invalid_language_code_raises_validation_error(tmp_path: Path) -> None:
    config_dir = copy_example_config_tree(tmp_path)
    materialise_primary_config_files(config_dir)
    write_file(
        config_dir / "policy.yaml",
        read_file(config_dir / "policy.yaml").replace("- eng", "- english", 1),
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config_bundle(project_root=tmp_path)

    assert exc_info.value.kind == "validation_error"
    assert any(detail.location.startswith("languages.preferred_audio") for detail in exc_info.value.details)


def test_invalid_profile_reference_raises_clear_error(tmp_path: Path) -> None:
    config_dir = copy_example_config_tree(tmp_path)
    materialise_primary_config_files(config_dir)
    write_file(
        config_dir / "policy.yaml",
        read_file(config_dir / "policy.yaml").replace("movies-default", "missing-profile", 1),
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config_bundle(project_root=tmp_path)

    assert exc_info.value.kind == "invalid_reference"
    assert any("missing-profile" in detail.message for detail in exc_info.value.details)


def test_environment_variables_override_config_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_dir = tmp_path / "custom-config"
    profiles_dir = custom_dir / "profiles"
    profiles_dir.mkdir(parents=True)

    write_file(custom_dir / "app-file.yaml", read_file(REPO_ROOT / "config" / "app.example.yaml"))
    write_file(custom_dir / "policy-file.yaml", read_file(REPO_ROOT / "config" / "policy.example.yaml"))
    write_file(custom_dir / "workers-file.yaml", read_file(REPO_ROOT / "config" / "workers.example.yaml"))
    for source in (REPO_ROOT / "config" / "profiles").glob("*.yaml"):
        shutil.copy(source, profiles_dir / source.name)

    monkeypatch.setenv(APP_CONFIG_PATH_ENV, str(custom_dir / "app-file.yaml"))
    monkeypatch.setenv(POLICY_CONFIG_PATH_ENV, str(custom_dir / "policy-file.yaml"))
    monkeypatch.setenv(WORKERS_CONFIG_PATH_ENV, str(custom_dir / "workers-file.yaml"))

    bundle = load_config_bundle(project_root=tmp_path)

    assert bundle.paths.app.from_environment is True
    assert bundle.paths.policy.from_environment is True
    assert bundle.paths.workers.from_environment is True
    assert bundle.paths.profiles_dir == profiles_dir.resolve()


def test_profile_directory_loading_returns_named_profiles(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)
    write_file(
        profiles_dir / "alpha.yaml",
        """
profile:
  name: alpha
  description: Alpha profile.
  audio:
    preserve_best_surround: true
""",
    )
    write_file(
        profiles_dir / "beta.yaml",
        """
profile:
  name: beta
  description: Beta profile.
  video:
    non_4k:
      preferred_codec: hevc
""",
    )

    loaded = load_profiles_from_directory(profiles_dir)

    assert set(loaded.profiles) == {"alpha", "beta"}
    assert loaded.sources["alpha"].name == "alpha.yaml"


def copy_example_config_tree(tmp_path: Path) -> Path:
    source = REPO_ROOT / "config"
    destination = tmp_path / "config"
    shutil.copytree(source, destination)
    return destination


def materialise_primary_config_files(config_dir: Path) -> None:
    write_file(config_dir / "app.yaml", read_file(config_dir / "app.example.yaml"))
    write_file(config_dir / "policy.yaml", read_file(config_dir / "policy.example.yaml"))
    write_file(config_dir / "workers.yaml", read_file(config_dir / "workers.example.yaml"))


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.lstrip("\n"), encoding="utf-8")
