from __future__ import annotations

from pathlib import Path

from encodr_core.config import ConfigBundle
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan, build_processing_plan


def build_media_processing_plan(
    media_file: MediaFile,
    config_bundle: ConfigBundle,
    *,
    source_path: Path | str | None = None,
) -> ProcessingPlan:
    return build_processing_plan(media_file, config_bundle, source_path=source_path)

