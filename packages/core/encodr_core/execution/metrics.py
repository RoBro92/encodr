from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path

from encodr_core.media.models import MediaFile


@dataclass(frozen=True, slots=True)
class BitrateMeasurement:
    value: int | None
    source: str | None
    unavailable_reason: str | None


def calculate_media_savings(
    source_media: MediaFile,
    output_media: MediaFile,
    *,
    ffprobe_path: Path | str | None = None,
) -> dict[str, float | int | None]:
    source_total_size = source_media.container.size_bytes
    output_total_size = output_media.container.size_bytes
    total_saved = None
    if source_total_size is not None and output_total_size is not None:
        total_saved = max(source_total_size - output_total_size, 0)

    source_sizes = estimate_stream_class_sizes(source_media, ffprobe_path=ffprobe_path)
    output_sizes = estimate_stream_class_sizes(output_media, ffprobe_path=ffprobe_path)
    source_video_size = source_sizes["video"]
    output_video_size = output_sizes["video"]
    source_non_video_size = source_sizes["non_video"]
    output_non_video_size = output_sizes["non_video"]

    video_saved = None
    if source_video_size is not None and output_video_size is not None:
        video_saved = source_video_size - output_video_size

    non_video_saved = None
    if source_non_video_size is not None and output_non_video_size is not None:
        non_video_saved = source_non_video_size - output_non_video_size

    if video_saved is None and total_saved is not None and non_video_saved is not None:
        video_saved = max(total_saved - non_video_saved, 0)
    if non_video_saved is None and total_saved is not None and video_saved is not None:
        non_video_saved = max(total_saved - video_saved, 0)

    compression_reduction_percent = None
    if source_video_size and video_saved is not None and source_video_size > 0:
        compression_reduction_percent = (video_saved / source_video_size) * 100.0

    source_bitrate = measure_video_bitrate(source_media, video_size_bytes=source_video_size, label="source")
    output_bitrate = measure_video_bitrate(output_media, video_size_bytes=output_video_size, label="output")

    return {
        "input_size_bytes": source_total_size,
        "output_size_bytes": output_total_size,
        "space_saved_bytes": total_saved,
        "video_input_size_bytes": source_video_size,
        "video_output_size_bytes": output_video_size,
        "video_space_saved_bytes": video_saved,
        "source_video_bitrate_bps": source_bitrate.value,
        "output_video_bitrate_bps": output_bitrate.value,
        "source_video_bitrate_source": source_bitrate.source,
        "output_video_bitrate_source": output_bitrate.source,
        "source_video_bitrate_unavailable_reason": source_bitrate.unavailable_reason,
        "output_video_bitrate_unavailable_reason": output_bitrate.unavailable_reason,
        "source_duration_seconds": source_media.container.duration_seconds,
        "output_duration_seconds": output_media.container.duration_seconds,
        "compression_reduction_unavailable_reason": compression_reduction_unavailable_reason(
            source_video_size=source_video_size,
            output_video_size=output_video_size,
        ),
        "non_video_space_saved_bytes": non_video_saved,
        "compression_reduction_percent": compression_reduction_percent,
    }


def estimate_stream_class_sizes(
    media: MediaFile,
    *,
    ffprobe_path: Path | str | None = None,
) -> dict[str, int | None]:
    video_size = estimate_stream_size_from_bitrate(media.video_streams, duration=media.container.duration_seconds)
    non_video_size = estimate_stream_size_from_bitrate(
        [*media.audio_streams, *media.subtitle_streams],
        duration=media.container.duration_seconds,
    )

    if ffprobe_path is not None and (video_size is None or non_video_size is None):
        packet_sizes = probe_packet_sizes_by_stream(media.file_path, ffprobe_path=ffprobe_path)
        if video_size is None:
            video_indices = {stream.index for stream in media.video_streams}
            video_size = sum_packet_sizes_if_present(packet_sizes, video_indices)
        if non_video_size is None:
            non_video_indices = {stream.index for stream in [*media.audio_streams, *media.subtitle_streams]}
            non_video_size = sum_packet_sizes_if_present(packet_sizes, non_video_indices)

    total_size = media.container.size_bytes
    if video_size is None and total_size is not None and non_video_size is not None:
        video_size = max(total_size - non_video_size, 0)
    if non_video_size is None and total_size is not None and video_size is not None:
        non_video_size = max(total_size - video_size, 0)

    return {
        "video": video_size,
        "non_video": non_video_size,
    }


def estimate_stream_size_from_bitrate(streams, *, duration: float | None) -> int | None:
    total = 0
    found = False
    if duration is None or duration <= 0:
        return None
    for stream in streams:
        bit_rate = getattr(stream, "bit_rate", None)
        if bit_rate is None:
            continue
        total += int((bit_rate * duration) / 8)
        found = True
    return total if found else None


def sum_packet_sizes_if_present(packet_sizes: dict[int, int], stream_indices: set[int]) -> int | None:
    if not any(index in packet_sizes for index in stream_indices):
        return None
    return sum(packet_sizes.get(index, 0) for index in stream_indices)


def first_video_bitrate(media: MediaFile) -> int | None:
    if not media.video_streams:
        return None
    return media.video_streams[0].bit_rate


def measure_video_bitrate(
    media: MediaFile,
    *,
    video_size_bytes: int | None,
    label: str,
) -> BitrateMeasurement:
    stream_bitrate = first_video_bitrate(media)
    if stream_bitrate is not None:
        return BitrateMeasurement(
            value=stream_bitrate,
            source="stream_bit_rate",
            unavailable_reason=None,
        )

    missing: list[str] = ["video stream bit_rate"]
    duration = media.container.duration_seconds
    if video_size_bytes is None:
        missing.append("video size")
    if duration is None or duration <= 0:
        missing.append("duration")
    if video_size_bytes is None or duration is None or duration <= 0:
        return BitrateMeasurement(
            value=None,
            source=None,
            unavailable_reason=(
                f"{label}_video_bitrate_bps is unavailable because ffprobe did not report "
                f"{_format_missing_values(missing)}."
            ),
        )

    return BitrateMeasurement(
        value=int(round((video_size_bytes * 8) / duration)),
        source="derived_video_size_duration",
        unavailable_reason=None,
    )


def compression_reduction_unavailable_reason(
    *,
    source_video_size: int | None,
    output_video_size: int | None,
) -> str | None:
    missing: list[str] = []
    if source_video_size is None:
        missing.append("source video size")
    if output_video_size is None:
        missing.append("output video size")
    if not missing:
        return None
    return f"compression_reduction_percent is unavailable because {_format_missing_values(missing)} could not be derived."


def _format_missing_values(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} or {values[1]}"
    return f"{', '.join(values[:-1])}, or {values[-1]}"


def probe_packet_sizes_by_stream(
    file_path: Path | str,
    *,
    ffprobe_path: Path | str,
    timeout_seconds: int = 60,
) -> dict[int, int]:
    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-show_entries",
        "packet=stream_index,size",
        "-of",
        "csv=p=0",
        str(file_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}

    packet_sizes: dict[int, int] = {}
    for line in result.stdout.splitlines():
        if not line:
            continue
        stream_index_text, _, size_text = line.partition(",")
        if not size_text:
            continue
        try:
            stream_index = int(stream_index_text)
            size = int(size_text)
        except ValueError:
            continue
        packet_sizes[stream_index] = packet_sizes.get(stream_index, 0) + size
    return packet_sizes


def estimate_video_size_bytes(media: MediaFile) -> int | None:
    total = 0
    found = False
    duration = media.container.duration_seconds
    if duration is None or duration <= 0:
        return None
    for stream in media.video_streams:
        if stream.bit_rate is None:
            continue
        total += int((stream.bit_rate * duration) / 8)
        found = True
    if found:
        return total
    return estimate_total_minus_non_video(media)


def estimate_non_video_size_bytes(media: MediaFile) -> int | None:
    total = 0
    found = False
    duration = media.container.duration_seconds
    if duration is None or duration <= 0:
        return None
    for stream in [*media.audio_streams, *media.subtitle_streams]:
        bit_rate = getattr(stream, "bit_rate", None)
        if bit_rate is None:
            continue
        total += int((bit_rate * duration) / 8)
        found = True
    if found:
        return total
    return None


def estimate_total_minus_non_video(media: MediaFile) -> int | None:
    total_size = media.container.size_bytes
    non_video = estimate_non_video_size_bytes(media)
    if total_size is None or non_video is None:
        return None
    return max(total_size - non_video, 0)
