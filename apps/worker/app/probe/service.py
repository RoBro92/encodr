from __future__ import annotations

from pathlib import Path

from encodr_core.media.models import MediaFile
from encodr_core.probe import FFprobeClient


def probe_media_file(file_path: Path | str, *, ffprobe_path: Path | str = "/usr/bin/ffprobe") -> MediaFile:
    client = FFprobeClient(binary_path=ffprobe_path)
    return client.probe_file(file_path)

