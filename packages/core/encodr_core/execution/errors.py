from __future__ import annotations

from pathlib import Path
from typing import Any


class ExecutionError(Exception):
    def __init__(
        self,
        message: str,
        *,
        file_path: Path | str | None = None,
        command: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.file_path = Path(file_path) if file_path is not None else None
        self.command = command
        self.details = details or {}
        super().__init__(self.__str__())

    def __str__(self) -> str:
        if self.file_path is None:
            return self.message
        return f"{self.message} ({self.file_path})"


class FFmpegBinaryNotFoundError(ExecutionError):
    pass


class FFmpegProcessError(ExecutionError):
    pass


class ExecutionBackendUnavailableError(ExecutionError):
    pass
