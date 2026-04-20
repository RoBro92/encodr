from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from encodr_core.config.app import AppConfig
from encodr_core.config.base import EnvironmentName

AUTH_SECRET_ENV = "ENCODR_AUTH_SECRET"


class AuthError(Exception):
    pass


class BootstrapDisabledError(AuthError):
    pass


class AuthenticationFailedError(AuthError):
    pass


class InactiveUserError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


@dataclass(frozen=True, slots=True)
class AuthRuntimeSettings:
    secret_key: str
    algorithm: str
    access_token_ttl: timedelta
    refresh_token_ttl: timedelta


def load_auth_runtime_settings(app_config: AppConfig) -> AuthRuntimeSettings:
    secret_key = os.environ.get(AUTH_SECRET_ENV)
    if not secret_key:
        if app_config.environment in {EnvironmentName.DEVELOPMENT, EnvironmentName.TESTING}:
            secret_key = "encodr-insecure-development-secret-change-me"
        else:
            raise RuntimeError(
                f"{AUTH_SECRET_ENV} must be set when running outside development or testing."
            )

    return AuthRuntimeSettings(
        secret_key=secret_key,
        algorithm=app_config.auth.access_token_algorithm,
        access_token_ttl=timedelta(minutes=app_config.auth.access_token_ttl_minutes),
        refresh_token_ttl=timedelta(days=app_config.auth.refresh_token_ttl_days),
    )
