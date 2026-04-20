from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from encodr_core.probe.client import FFprobeClient
    from encodr_core.probe.errors import (
        ProbeBinaryNotFoundError,
        ProbeDataError,
        ProbeError,
        ProbeErrorDetail,
        ProbeInvalidJsonError,
        ProbeProcessError,
    )
    from encodr_core.probe.parser import parse_ffprobe_json_output, parse_ffprobe_payload

__all__ = [
    "FFprobeClient",
    "ProbeBinaryNotFoundError",
    "ProbeDataError",
    "ProbeError",
    "ProbeErrorDetail",
    "ProbeInvalidJsonError",
    "ProbeProcessError",
    "parse_ffprobe_json_output",
    "parse_ffprobe_payload",
]


def __getattr__(name: str) -> Any:
    if name == "FFprobeClient":
        from encodr_core.probe.client import FFprobeClient

        return FFprobeClient
    if name in {
        "ProbeBinaryNotFoundError",
        "ProbeDataError",
        "ProbeError",
        "ProbeErrorDetail",
        "ProbeInvalidJsonError",
        "ProbeProcessError",
    }:
        from encodr_core.probe.errors import (
            ProbeBinaryNotFoundError,
            ProbeDataError,
            ProbeError,
            ProbeErrorDetail,
            ProbeInvalidJsonError,
            ProbeProcessError,
        )

        return {
            "ProbeBinaryNotFoundError": ProbeBinaryNotFoundError,
            "ProbeDataError": ProbeDataError,
            "ProbeError": ProbeError,
            "ProbeErrorDetail": ProbeErrorDetail,
            "ProbeInvalidJsonError": ProbeInvalidJsonError,
            "ProbeProcessError": ProbeProcessError,
        }[name]
    if name in {"parse_ffprobe_json_output", "parse_ffprobe_payload"}:
        from encodr_core.probe.parser import parse_ffprobe_json_output, parse_ffprobe_payload

        return {
            "parse_ffprobe_json_output": parse_ffprobe_json_output,
            "parse_ffprobe_payload": parse_ffprobe_payload,
        }[name]
    raise AttributeError(name)
