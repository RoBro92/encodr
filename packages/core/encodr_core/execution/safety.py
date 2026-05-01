from __future__ import annotations

from dataclasses import dataclass

from encodr_core.media.quality import format_bitrate
from encodr_core.planning.models import ProcessingPlan


@dataclass(frozen=True, slots=True)
class ExecutionSafetyFailure:
    category: str
    message: str


def evaluate_execution_safety(
    *,
    plan: ProcessingPlan,
    metrics: dict[str, float | int | None],
) -> ExecutionSafetyFailure | None:
    output_larger_failure = _output_larger_than_input_failure(plan=plan, metrics=metrics)
    if output_larger_failure is not None:
        return output_larger_failure

    if not plan.video.transcode_required:
        return None

    reduction_limit = plan.video.max_allowed_video_reduction_percent
    if reduction_limit is None:
        return None

    reduction = metrics.get("compression_reduction_percent")
    if reduction is None:
        return ExecutionSafetyFailure(
            category="compression_safety_unmeasurable",
            message="Video reduction could not be measured safely, so the output requires manual review.",
        )

    output_bitrate = _number(metrics.get("output_video_bitrate_bps"))
    minimum_bitrate = _number(plan.video.minimum_output_bitrate_bps)
    if minimum_bitrate is not None and output_bitrate is not None and output_bitrate < minimum_bitrate:
        return ExecutionSafetyFailure(
            category="compression_safety_bitrate_floor",
            message=(
                "Encoded video bitrate is below the configured quality safeguard "
                f"({format_bitrate(output_bitrate)} < {format_bitrate(minimum_bitrate)})."
            ),
        )

    if reduction <= reduction_limit:
        return None

    if minimum_bitrate is not None and output_bitrate is not None and output_bitrate >= minimum_bitrate:
        return None

    if minimum_bitrate is None or output_bitrate is None:
        return ExecutionSafetyFailure(
            category="compression_safety_unmeasurable",
            message=(
                f"Video compression reduced the picture by {float(reduction):.1f}%, above the "
                f"configured review threshold of {reduction_limit}%, but output bitrate could not "
                "be measured against a quality floor."
            ),
        )

    return ExecutionSafetyFailure(
        category="compression_safety_exceeded",
        message=(
            f"Video compression reduced the picture by {float(reduction):.1f}% and output bitrate "
            f"{format_bitrate(output_bitrate)} is below the configured safeguard "
            f"{format_bitrate(minimum_bitrate)}."
        ),
    )


def _output_larger_than_input_failure(
    *,
    plan: ProcessingPlan,
    metrics: dict[str, float | int | None],
) -> ExecutionSafetyFailure | None:
    guard_percent = plan.video.output_larger_than_input_review_percent
    if guard_percent is None:
        return None
    input_size = _number(metrics.get("input_size_bytes"))
    output_size = _number(metrics.get("output_size_bytes"))
    if input_size is None or output_size is None or input_size <= 0:
        return None
    allowed_size = input_size * (1 + (guard_percent / 100.0))
    if output_size <= allowed_size:
        return None
    growth_percent = ((output_size - input_size) / input_size) * 100.0
    return ExecutionSafetyFailure(
        category="output_larger_than_input",
        message=(
            f"Output grew by {growth_percent:.1f}%, exceeding configured guard of {guard_percent}%."
        ),
    )


def _number(value: float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)
