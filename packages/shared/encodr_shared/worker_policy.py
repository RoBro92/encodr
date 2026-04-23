from __future__ import annotations

from typing import Iterable


def recommend_worker_concurrency(*, cpu_count: int | None, hardware_hints: Iterable[str] | None = None) -> tuple[int, str]:
    hints = {str(item) for item in (hardware_hints or [])}
    cores = max(1, int(cpu_count or 1))
    if hints & {"nvidia_gpu", "amd_gpu", "intel_igpu"}:
        recommendation = max(1, min(3, cores // 4 or 1))
        return recommendation, "Recommended from detected hardware acceleration and available CPU cores."
    recommendation = max(1, min(2, cores // 6 or 1))
    return recommendation, "Recommended from CPU-only execution and available cores."

