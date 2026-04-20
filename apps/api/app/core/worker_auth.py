from __future__ import annotations

import os
from dataclasses import dataclass

from encodr_core.config.app import AppConfig
from encodr_core.config.base import EnvironmentName

WORKER_REGISTRATION_SECRET_ENV = "ENCODR_WORKER_REGISTRATION_SECRET"


@dataclass(frozen=True, slots=True)
class WorkerAuthRuntimeSettings:
    registration_secret: str


def load_worker_auth_runtime_settings(app_config: AppConfig) -> WorkerAuthRuntimeSettings:
    registration_secret = os.environ.get(WORKER_REGISTRATION_SECRET_ENV)
    if not registration_secret:
        if app_config.environment in {EnvironmentName.DEVELOPMENT, EnvironmentName.TESTING}:
            registration_secret = "encodr-insecure-worker-registration-secret-change-me"
        else:
            raise RuntimeError(
                f"{WORKER_REGISTRATION_SECRET_ENV} must be set when running outside development or testing."
            )
    return WorkerAuthRuntimeSettings(registration_secret=registration_secret)
