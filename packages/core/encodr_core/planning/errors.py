from __future__ import annotations

from pathlib import Path
from typing import Any


class PlanningError(Exception):
    def __init__(
        self,
        message: str,
        *,
        source_path: Path | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.source_path = Path(source_path) if source_path is not None else None
        self.details = details or {}
        super().__init__(self.__str__())

    def __str__(self) -> str:
        if self.source_path is None:
            return self.message
        return f"{self.message} ({self.source_path})"

