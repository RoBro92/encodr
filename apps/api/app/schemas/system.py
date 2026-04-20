from __future__ import annotations

from pydantic import BaseModel


class PathStatusResponse(BaseModel):
    path: str
    exists: bool
    is_directory: bool
    readable: bool
    writable: bool


class StorageStatusResponse(BaseModel):
    scratch: PathStatusResponse
    data_dir: PathStatusResponse
    media_mounts: list[PathStatusResponse]


class RuntimeStatusResponse(BaseModel):
    version: str
    environment: str
    db_reachable: bool
    auth_enabled: bool
    api_base_path: str
    scratch_dir: str
    data_dir: str
    media_mounts: list[str]
