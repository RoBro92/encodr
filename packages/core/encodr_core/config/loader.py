from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import ValidationError

from encodr_core.config.app import AppConfigDocument
from encodr_core.config.base import ConfigModel
from encodr_core.config.errors import ConfigError, ConfigErrorDetail
from encodr_core.config.policy import PolicyConfig
from encodr_core.config.profiles import LoadedProfiles, ProfileConfigDocument
from encodr_core.config.workers import WorkersConfigDocument

ConfigModelT = TypeVar("ConfigModelT", bound=ConfigModel)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError.missing_file(path)

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigError.malformed_yaml(path, error) from error

    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise ConfigError.validation_error(
            path,
            "Configuration file must contain a YAML mapping at the top level.",
            details=[
                ConfigErrorDetail(
                    location="root",
                    message="Expected a YAML mapping.",
                    input_value=type(raw).__name__,
                )
            ],
        )

    return raw


def load_model(path: Path, model_type: type[ConfigModelT], *, message: str) -> ConfigModelT:
    raw = load_yaml_mapping(path)
    try:
        return model_type.model_validate(raw)
    except ValidationError as error:
        raise ConfigError.from_validation_error(path, error, message=message) from error


def load_app_config(path: Path) -> AppConfigDocument:
    return load_model(
        path,
        AppConfigDocument,
        message="App configuration is invalid.",
    )


def load_policy_config(path: Path) -> PolicyConfig:
    return load_model(
        path,
        PolicyConfig,
        message="Policy configuration is invalid.",
    )


def load_workers_config(path: Path) -> WorkersConfigDocument:
    return load_model(
        path,
        WorkersConfigDocument,
        message="Worker configuration is invalid.",
    )


def load_profiles_from_directory(directory: Path) -> LoadedProfiles:
    if not directory.exists():
        return LoadedProfiles(profiles={}, sources={})

    if not directory.is_dir():
        raise ConfigError.validation_error(
            directory,
            "Profiles path must be a directory.",
            details=[ConfigErrorDetail(location="profiles_dir", message="Expected a directory.")],
        )

    profiles: dict[str, Any] = {}
    sources: dict[str, Path] = {}
    profile_files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix in {".yaml", ".yml"}
    )

    for path in profile_files:
        document = load_model(
            path,
            ProfileConfigDocument,
            message="Profile configuration is invalid.",
        )
        profile = document.profile
        if profile.name in profiles:
            raise ConfigError.invalid_reference(
                path,
                f"Duplicate profile name '{profile.name}' detected.",
                details=[
                    ConfigErrorDetail(
                        location="profile.name",
                        message=f"Profile name '{profile.name}' is already defined.",
                        input_value=str(sources[profile.name]),
                    )
                ],
            )
        profiles[profile.name] = profile
        sources[profile.name] = path

    return LoadedProfiles(profiles=profiles, sources=sources)

