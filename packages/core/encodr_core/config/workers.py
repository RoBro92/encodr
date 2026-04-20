from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from encodr_core.config.base import (
    ConfigModel,
    NonEmptyString,
    PositiveInt,
    RemoteWorkerAuthMode,
)


class WorkerCapabilities(ConfigModel):
    ffmpeg: bool
    ffprobe: bool
    intel_qsv: bool = False
    nvenc: bool = False
    vaapi: bool = False
    amd_amf: bool = False


class LocalWorkerConfig(ConfigModel):
    id: NonEmptyString
    enabled: bool = True
    type: Literal["local"]
    host: NonEmptyString
    queue: NonEmptyString
    scratch_dir: Path
    media_mounts: list[Path] = Field(default_factory=list)
    max_concurrent_jobs: PositiveInt = 1
    capabilities: WorkerCapabilities


class RemoteWorkerConfig(ConfigModel):
    id: NonEmptyString
    enabled: bool = True
    type: Literal["remote"]
    queue: NonEmptyString
    endpoint: AnyHttpUrl
    auth_mode: RemoteWorkerAuthMode = RemoteWorkerAuthMode.MTLS
    max_concurrent_jobs: PositiveInt = 1
    capabilities: WorkerCapabilities
    notes: str | None = None

    @field_validator("auth_mode", mode="before")
    @classmethod
    def normalise_auth_mode(cls, value: Any) -> Any:
        return RemoteWorkerAuthMode.normalise(value)


class WorkersConfig(ConfigModel):
    default_queue: NonEmptyString
    local: LocalWorkerConfig
    remote: list[RemoteWorkerConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_default_queue(self) -> "WorkersConfig":
        valid_queues = {self.local.queue}
        valid_queues.update(worker.queue for worker in self.remote)
        if self.default_queue not in valid_queues:
            raise ValueError(
                f"default_queue '{self.default_queue}' does not match any declared worker queue."
            )
        return self


class WorkersConfigDocument(ConfigModel):
    workers: WorkersConfig
