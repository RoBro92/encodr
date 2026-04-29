from __future__ import annotations

from encodr_core.media.models import VideoStream

DEFAULT_LOW_BITRATE_1080P_MBPS = 3.0
DEFAULT_LOW_BITRATE_720P_MBPS = 1.5
DEFAULT_MIN_OUTPUT_1080P_MBPS = 1.75
DEFAULT_MIN_OUTPUT_720P_MBPS = 1.0
DEFAULT_OUTPUT_LARGER_THAN_INPUT_REVIEW_PERCENT = 5


def mbps_to_bps(value: float | int | None) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 1_000_000))


def stream_height(video_stream: VideoStream) -> int | None:
    return video_stream.height or video_stream.coded_height


def resolution_bucket(video_stream: VideoStream) -> str:
    height = stream_height(video_stream)
    if height is None:
        width = video_stream.width or video_stream.coded_width
        if width is not None and width <= 1280:
            return "720p"
        return "1080p"
    if height <= 720:
        return "720p"
    return "1080p"


def low_bitrate_threshold_bps(
    video_stream: VideoStream,
    *,
    threshold_1080p_mbps: float | int | None,
    threshold_720p_mbps: float | int | None,
) -> int | None:
    threshold = threshold_720p_mbps if resolution_bucket(video_stream) == "720p" else threshold_1080p_mbps
    return mbps_to_bps(threshold)


def minimum_output_bitrate_bps(
    video_stream: VideoStream,
    *,
    floor_1080p_mbps: float | int | None,
    floor_720p_mbps: float | int | None,
) -> int | None:
    floor = floor_720p_mbps if resolution_bucket(video_stream) == "720p" else floor_1080p_mbps
    return mbps_to_bps(floor)


def is_low_bitrate_source(video_stream: VideoStream, threshold_bps: int | None) -> bool:
    return threshold_bps is not None and video_stream.bit_rate is not None and video_stream.bit_rate < threshold_bps


def format_bitrate(bps: float | int | None) -> str:
    if bps is None:
        return "unknown"
    mbps = float(bps) / 1_000_000
    if mbps >= 10:
        return f"{mbps:.1f} Mbps"
    return f"{mbps:.2f} Mbps"
