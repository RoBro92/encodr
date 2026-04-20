from __future__ import annotations

from pathlib import Path
from typing import Any


class ProbeErrorDetail:
    def __init__(self, *, location: str, message: str, input_value: Any | None = None) -> None:
        self.location = location
        self.message = message
        self.input_value = input_value

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "location": self.location,
            "message": self.message,
        }
        if self.input_value is not None:
            payload["input_value"] = self.input_value
        return payload


class ProbeError(Exception):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        file_path: Path | str | None = None,
        binary_path: Path | str | None = None,
        exit_code: int | None = None,
        stderr: str | None = None,
        details: list[ProbeErrorDetail] | None = None,
    ) -> None:
        self.kind = kind
        self.message = message
        self.file_path = Path(file_path) if file_path is not None else None
        self.binary_path = Path(binary_path) if binary_path is not None else None
        self.exit_code = exit_code
        self.stderr = stderr
        self.details = details or []
        super().__init__(self.__str__())

    def __str__(self) -> str:
        if self.file_path is None:
            return self.message
        return f"{self.message} ({self.file_path})"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "message": self.message,
            "details": [detail.to_dict() for detail in self.details],
        }
        if self.file_path is not None:
            payload["file_path"] = str(self.file_path)
        if self.binary_path is not None:
            payload["binary_path"] = str(self.binary_path)
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        if self.stderr:
            payload["stderr"] = self.stderr
        return payload


class ProbeBinaryNotFoundError(ProbeError):
    def __init__(self, *, binary_path: Path | str, file_path: Path | str | None = None) -> None:
        super().__init__(
            "probe_binary_missing",
            "ffprobe binary could not be found.",
            file_path=file_path,
            binary_path=binary_path,
        )


class ProbeProcessError(ProbeError):
    def __init__(
        self,
        *,
        file_path: Path | str,
        binary_path: Path | str,
        exit_code: int,
        stderr: str | None = None,
    ) -> None:
        super().__init__(
            "probe_process_failed",
            "ffprobe returned a non-zero exit status.",
            file_path=file_path,
            binary_path=binary_path,
            exit_code=exit_code,
            stderr=stderr,
        )


class ProbeInvalidJsonError(ProbeError):
    def __init__(self, *, file_path: Path | str, details: list[ProbeErrorDetail] | None = None) -> None:
        super().__init__(
            "probe_invalid_json",
            "ffprobe did not return valid JSON output.",
            file_path=file_path,
            details=details,
        )


class ProbeDataError(ProbeError):
    def __init__(
        self,
        message: str,
        *,
        file_path: Path | str | None = None,
        details: list[ProbeErrorDetail] | None = None,
    ) -> None:
        super().__init__(
            "probe_data_invalid",
            message,
            file_path=file_path,
            details=details,
        )

