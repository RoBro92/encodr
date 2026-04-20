from __future__ import annotations

from typing import Any

from encodr_core.planning.models import PlanReason, PlanWarning


def make_reason(code: str, message: str, **metadata: Any) -> PlanReason:
    return PlanReason(code=code, message=message, metadata=metadata)


def make_warning(code: str, message: str, **metadata: Any) -> PlanWarning:
    return PlanWarning(code=code, message=message, metadata=metadata)

