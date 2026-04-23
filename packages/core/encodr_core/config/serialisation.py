from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from encodr_core.config.app import AppConfig
from encodr_core.config.bootstrap import ConfigBundle, ResolvedConfigFile, ResolvedConfigPaths
from encodr_core.config.policy import PolicyConfig
from encodr_core.config.profiles import ProfileConfig
from encodr_core.config.workers import WorkersConfig


def serialise_config_bundle(config_bundle: ConfigBundle) -> dict[str, Any]:
    return {
        "app": config_bundle.app.model_dump(mode="json"),
        "policy": config_bundle.policy.model_dump(mode="json"),
        "workers": config_bundle.workers.model_dump(mode="json"),
        "profiles": {
            name: profile.model_dump(mode="json")
            for name, profile in config_bundle.profiles.items()
        },
    }


def deserialise_config_bundle(payload: Mapping[str, Any]) -> ConfigBundle:
    placeholder = Path(".encodr-runtime-placeholder").resolve()
    return ConfigBundle(
        app=AppConfig.model_validate(payload["app"]),
        policy=PolicyConfig.model_validate(payload["policy"]),
        workers=WorkersConfig.model_validate(payload["workers"]),
        profiles={
            name: ProfileConfig.model_validate(profile_payload)
            for name, profile_payload in dict(payload.get("profiles", {})).items()
        },
        profile_sources={},
        paths=ResolvedConfigPaths(
            app=ResolvedConfigFile(
                requested_path=placeholder,
                resolved_path=placeholder,
                used_example_fallback=False,
                from_environment=False,
            ),
            policy=ResolvedConfigFile(
                requested_path=placeholder,
                resolved_path=placeholder,
                used_example_fallback=False,
                from_environment=False,
            ),
            workers=ResolvedConfigFile(
                requested_path=placeholder,
                resolved_path=placeholder,
                used_example_fallback=False,
                from_environment=False,
            ),
            profiles_dir=placeholder,
        ),
    )
