from __future__ import annotations

from time import monotonic
from typing import Any

from encodr_shared import redact_secrets


def elapsed_ms(started_at: float) -> int:
    return max(0, int((monotonic() - started_at) * 1000))


def safe_reason(reason: object, *, limit: int = 500) -> str:
    cleaned = redact_secrets(str(reason).strip())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit - 1]}..."


def exception_fields(error: BaseException) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "exception_type": type(error).__name__,
        "reason": safe_reason(error),
    }
    errno_value = getattr(error, "errno", None)
    if errno_value is not None:
        fields["errno"] = errno_value
    return fields
