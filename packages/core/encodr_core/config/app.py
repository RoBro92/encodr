from __future__ import annotations

from pydantic import AnyUrl, Field, model_validator

from encodr_core.config.base import (
    ConfigModel,
    EnvironmentName,
    FilesystemPath,
    LogLevel,
    NonEmptyString,
    PositiveInt,
    SessionMode,
    OutputContainer,
)


class AppOutputSettings(ConfigModel):
    return_to_original_folder: bool = True
    default_container: OutputContainer = OutputContainer.MKV


class ApiSettings(ConfigModel):
    host: NonEmptyString
    port: PositiveInt
    base_path: NonEmptyString = "/api"


class UiSettings(ConfigModel):
    public_url: AnyUrl


class AuthSettings(ConfigModel):
    enabled: bool = True
    session_mode: SessionMode = SessionMode.JWT
    access_token_ttl_minutes: PositiveInt = 30
    refresh_token_ttl_days: PositiveInt = 14
    password_hash_scheme: NonEmptyString = "argon2id"


class DatabaseSettings(ConfigModel):
    dsn: NonEmptyString


class RedisSettings(ConfigModel):
    url: NonEmptyString


class MediaToolSettings(ConfigModel):
    ffprobe_path: FilesystemPath
    ffmpeg_path: FilesystemPath
    verify_outputs: bool = True
    keep_job_artifacts: bool = False


class DashboardSettings(ConfigModel):
    recent_job_limit: PositiveInt = 25
    analytics_window_days: PositiveInt = 30


class AppConfig(ConfigModel):
    name: NonEmptyString
    environment: EnvironmentName = EnvironmentName.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    timezone: NonEmptyString
    data_dir: FilesystemPath
    scratch_dir: FilesystemPath
    output: AppOutputSettings = Field(default_factory=AppOutputSettings)
    api: ApiSettings
    ui: UiSettings
    auth: AuthSettings = Field(default_factory=AuthSettings)
    database: DatabaseSettings
    redis: RedisSettings
    media: MediaToolSettings
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)

    @model_validator(mode="after")
    def validate_paths(self) -> "AppConfig":
        if self.scratch_dir == self.data_dir:
            raise ValueError("scratch_dir must be separate from data_dir.")
        return self


class AppConfigDocument(ConfigModel):
    app: AppConfig

