from __future__ import annotations

import subprocess
from pathlib import Path

from encodr_core.media.models import MediaFile


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

    return {
        "input_size_bytes": source_total_size,
        "output_size_bytes": output_total_size,
        "space_saved_bytes": total_saved,
        "video_input_size_bytes": source_video_size,
        "video_output_size_bytes": output_video_size,
        "video_space_saved_bytes": video_saved,
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
            video_size = sum(packet_sizes.get(index, 0) for index in video_indices)
        if non_video_size is None:
            non_video_indices = {stream.index for stream in [*media.audio_streams, *media.subtitle_streams]}
            non_video_size = sum(packet_sizes.get(index, 0) for index in non_video_indices)

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


def probe_packet_sizes_by_stream(
    file_path: Path | str,
    *,
    ffprobe_path: Path | str,
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
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
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
