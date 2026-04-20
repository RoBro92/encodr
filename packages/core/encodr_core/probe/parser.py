from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from encodr_core.media.models import MediaFile
from encodr_core.media.normalise import normalise_ffprobe_payload
from encodr_core.probe.errors import ProbeErrorDetail, ProbeInvalidJsonError


def parse_ffprobe_json_output(output: str | bytes, *, file_path: Path | str) -> MediaFile:
    text_output = output.decode("utf-8") if isinstance(output, bytes) else output
    try:
        payload = json.loads(text_output)
    except json.JSONDecodeError as error:
        raise ProbeInvalidJsonError(
            file_path=file_path,
            details=[
                ProbeErrorDetail(
                    location=f"line {error.lineno}, column {error.colno}",
                    message=error.msg,
                )
            ],
        ) from error

    if not isinstance(payload, dict):
        raise ProbeInvalidJsonError(
            file_path=file_path,
            details=[ProbeErrorDetail(location="root", message="Expected a JSON object.")],
        )

    return normalise_ffprobe_payload(payload, file_path=file_path)


def parse_ffprobe_payload(payload: dict[str, Any], *, file_path: Path | str) -> MediaFile:
    return normalise_ffprobe_payload(payload, file_path=file_path)

