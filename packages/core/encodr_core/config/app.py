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
from encodr_shared.update import DEFAULT_RELEASE_METADATA_URL


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
    access_token_algorithm: NonEmptyString = "HS256"


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


class UpdateSettings(ConfigModel):
    enabled: bool = True
    metadata_url: AnyUrl | None = Field(default=DEFAULT_RELEASE_METADATA_URL)
    channel: NonEmptyString = "internal"
    check_timeout_seconds: PositiveInt = 5

    @model_validator(mode="after")
    def migrate_legacy_defaults(self) -> "UpdateSettings":
        if self.enabled is False and self.metadata_url is None and self.channel == "internal":
            self.enabled = True
            self.metadata_url = DEFAULT_RELEASE_METADATA_URL
        return self


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
    update: UpdateSettings = Field(default_factory=UpdateSettings)

    @model_validator(mode="after")
    def validate_paths(self) -> "AppConfig":
        if self.scratch_dir == self.data_dir:
            raise ValueError("scratch_dir must be separate from data_dir.")
        return self


class AppConfigDocument(ConfigModel):
    app: AppConfig
