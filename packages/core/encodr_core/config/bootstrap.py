from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from encodr_core.config.app import AppConfig
from encodr_core.config.loader import (
    load_app_config,
    load_policy_config,
    load_profiles_from_directory,
    load_workers_config,
)
from encodr_core.config.policy import PolicyConfig
from encodr_core.config.profiles import ProfileConfig, validate_policy_profile_references
from encodr_core.config.workers import WorkersConfig

APP_CONFIG_PATH_ENV = "ENCODR_APP_CONFIG_FILE"
POLICY_CONFIG_PATH_ENV = "ENCODR_POLICY_CONFIG_FILE"
WORKERS_CONFIG_PATH_ENV = "ENCODR_WORKERS_CONFIG_FILE"


@dataclass(frozen=True, slots=True)
class ResolvedConfigFile:
    requested_path: Path
    resolved_path: Path
    used_example_fallback: bool
    from_environment: bool


@dataclass(frozen=True, slots=True)
class ResolvedConfigPaths:
    app: ResolvedConfigFile
    policy: ResolvedConfigFile
    workers: ResolvedConfigFile
    profiles_dir: Path


@dataclass(frozen=True, slots=True)
class ConfigBundle:
    app: AppConfig
    policy: PolicyConfig
    workers: WorkersConfig
    profiles: Mapping[str, ProfileConfig]
    profile_sources: Mapping[str, Path]
    paths: ResolvedConfigPaths


def load_config_bundle(
    *,
    project_root: Path | str | None = None,
    app_config_path: Path | str | None = None,
    policy_config_path: Path | str | None = None,
    workers_config_path: Path | str | None = None,
    profiles_dir: Path | str | None = None,
) -> ConfigBundle:
    root_dir = Path(project_root or Path.cwd()).resolve()
    config_dir = root_dir / "config"

    resolved_app = resolve_config_file(
        config_dir=config_dir,
        file_name="app.yaml",
        example_file_name="app.example.yaml",
        env_var_name=APP_CONFIG_PATH_ENV,
        explicit_path=app_config_path,
    )
    resolved_policy = resolve_config_file(
        config_dir=config_dir,
        file_name="policy.yaml",
        example_file_name="policy.example.yaml",
        env_var_name=POLICY_CONFIG_PATH_ENV,
        explicit_path=policy_config_path,
    )
    resolved_workers = resolve_config_file(
        config_dir=config_dir,
        file_name="workers.yaml",
        example_file_name="workers.example.yaml",
        env_var_name=WORKERS_CONFIG_PATH_ENV,
        explicit_path=workers_config_path,
    )
    resolved_profiles_dir = (
        Path(profiles_dir).resolve()
        if profiles_dir is not None
        else (resolved_policy.resolved_path.parent / "profiles").resolve()
    )

    app = load_app_config(resolved_app.resolved_path).app
    policy = load_policy_config(resolved_policy.resolved_path)
    workers = load_workers_config(resolved_workers.resolved_path).workers
    loaded_profiles = load_profiles_from_directory(resolved_profiles_dir)
    validate_policy_profile_references(
        policy,
        loaded_profiles.profiles,
        source=resolved_policy.resolved_path,
    )

    return ConfigBundle(
        app=app,
        policy=policy,
        workers=workers,
        profiles=loaded_profiles.profiles,
        profile_sources=loaded_profiles.sources,
        paths=ResolvedConfigPaths(
            app=resolved_app,
            policy=resolved_policy,
            workers=resolved_workers,
            profiles_dir=resolved_profiles_dir,
        ),
    )


def resolve_config_file(
    *,
    config_dir: Path,
    file_name: str,
    example_file_name: str,
    env_var_name: str,
    explicit_path: Path | str | None,
) -> ResolvedConfigFile:
    env_value = os.environ.get(env_var_name)
    if env_value:
        env_path = Path(env_value).expanduser().resolve()
        return ResolvedConfigFile(
            requested_path=env_path,
            resolved_path=env_path,
            used_example_fallback=False,
            from_environment=True,
        )

    if explicit_path is not None:
        resolved = Path(explicit_path).expanduser().resolve()
        return ResolvedConfigFile(
            requested_path=resolved,
            resolved_path=resolved,
            used_example_fallback=False,
            from_environment=False,
        )

    requested = (config_dir / file_name).resolve()
    if requested.exists():
        return ResolvedConfigFile(
            requested_path=requested,
            resolved_path=requested,
            used_example_fallback=False,
            from_environment=False,
        )

    example = (config_dir / example_file_name).resolve()
    if example.exists():
        return ResolvedConfigFile(
            requested_path=requested,
            resolved_path=example,
            used_example_fallback=True,
            from_environment=False,
        )

    return ResolvedConfigFile(
        requested_path=requested,
        resolved_path=requested,
        used_example_fallback=False,
        from_environment=False,
    )

