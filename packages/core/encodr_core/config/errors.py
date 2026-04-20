from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError
from yaml import MarkedYAMLError


@dataclass(frozen=True, slots=True)
class ConfigErrorDetail:
    location: str
    message: str
    input_value: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "location": self.location,
            "message": self.message,
        }
        if self.input_value is not None:
            payload["input_value"] = self.input_value
        return payload


@dataclass(slots=True)
class ConfigError(Exception):
    kind: str
    message: str
    source: Path | None = None
    details: list[ConfigErrorDetail] = field(default_factory=list)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.__str__())

    def __str__(self) -> str:
        if self.source is None:
            return self.message
        return f"{self.message} ({self.source})"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "message": self.message,
            "details": [detail.to_dict() for detail in self.details],
        }
        if self.source is not None:
            payload["source"] = str(self.source)
        return payload

    @classmethod
    def missing_file(cls, source: Path, *, message: str | None = None) -> "ConfigError":
        return cls(
            kind="missing_file",
            message=message or "Configuration file could not be found.",
            source=source,
        )

    @classmethod
    def malformed_yaml(cls, source: Path, error: MarkedYAMLError) -> "ConfigError":
        location = "yaml"
        if error.problem_mark is not None:
            location = f"line {error.problem_mark.line + 1}, column {error.problem_mark.column + 1}"
        return cls(
            kind="malformed_yaml",
            message="Configuration file contains malformed YAML.",
            source=source,
            details=[
                ConfigErrorDetail(
                    location=location,
                    message=error.problem or str(error),
                )
            ],
        )

    @classmethod
    def validation_error(
        cls,
        source: Path | None,
        message: str,
        *,
        details: Iterable[ConfigErrorDetail],
    ) -> "ConfigError":
        return cls(
            kind="validation_error",
            message=message,
            source=source,
            details=list(details),
        )

    @classmethod
    def invalid_reference(
        cls,
        source: Path | None,
        message: str,
        *,
        details: Iterable[ConfigErrorDetail],
    ) -> "ConfigError":
        return cls(
            kind="invalid_reference",
            message=message,
            source=source,
            details=list(details),
        )

    @classmethod
    def from_validation_error(
        cls,
        source: Path | None,
        error: ValidationError,
        *,
        message: str,
    ) -> "ConfigError":
        details = [
            ConfigErrorDetail(
                location=stringify_location(item["loc"]),
                message=item["msg"],
                input_value=item.get("input"),
            )
            for item in error.errors()
        ]
        return cls.validation_error(source, message, details=details)


def stringify_location(location: tuple[Any, ...] | list[Any] | str) -> str:
    if isinstance(location, str):
        return location

    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            if not parts:
                parts.append(f"[{item}]")
            else:
                parts[-1] = f"{parts[-1]}[{item}]"
            continue
        parts.append(str(item))
    return ".".join(parts)
