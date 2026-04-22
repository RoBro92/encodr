from __future__ import annotations

import pytest

from encodr_shared.telemetry import collect_runtime_telemetry


pytestmark = [pytest.mark.unit]


def test_collect_runtime_telemetry_includes_nvidia_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("encodr_shared.telemetry._sample_system_cpu_percent", lambda: 42.5)
    monkeypatch.setattr("encodr_shared.telemetry._sample_process_cpu_percent", lambda: 11.0)
    monkeypatch.setattr(
        "encodr_shared.telemetry._sample_memory",
        lambda: {
            "total_bytes": 1024,
            "available_bytes": 512,
            "used_bytes": 512,
            "usage_percent": 50.0,
        },
    )
    monkeypatch.setattr("encodr_shared.telemetry._sample_process_memory_bytes", lambda: 256)
    monkeypatch.setattr("encodr_shared.telemetry._sample_cpu_temperature_c", lambda: 61.2)
    monkeypatch.setattr(
        "encodr_shared.telemetry._sample_nvidia_telemetry",
        lambda: {
            "vendor": "NVIDIA",
            "status": "healthy",
            "usage_percent": 73.0,
            "temperature_c": 68.0,
            "memory_used_bytes": 1024,
            "memory_total_bytes": 2048,
            "message": "Telemetry is being read from nvidia-smi.",
        },
    )

    telemetry = collect_runtime_telemetry(current_backend="nvidia_gpu")

    assert telemetry["backend_in_use"] == "nvidia_gpu"
    assert telemetry["cpu_usage_percent"] == 42.5
    assert telemetry["memory_usage_percent"] == 50.0
    assert telemetry["gpu"]["vendor"] == "NVIDIA"
    assert telemetry["gpu"]["usage_percent"] == 73.0


def test_collect_runtime_telemetry_reports_unavailable_gpu_for_intel_without_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("encodr_shared.telemetry._sample_system_cpu_percent", lambda: None)
    monkeypatch.setattr("encodr_shared.telemetry._sample_process_cpu_percent", lambda: None)
    monkeypatch.setattr(
        "encodr_shared.telemetry._sample_memory",
        lambda: {
            "total_bytes": None,
            "available_bytes": None,
            "used_bytes": None,
            "usage_percent": None,
        },
    )
    monkeypatch.setattr("encodr_shared.telemetry._sample_process_memory_bytes", lambda: None)
    monkeypatch.setattr("encodr_shared.telemetry._sample_cpu_temperature_c", lambda: None)
    monkeypatch.setattr("encodr_shared.telemetry._sample_nvidia_telemetry", lambda: None)
    monkeypatch.setattr("encodr_shared.telemetry._sample_linux_drm_temperature", lambda _backend: None)

    telemetry = collect_runtime_telemetry(current_backend="intel_igpu")

    assert telemetry["gpu"]["vendor"] == "Intel"
    assert telemetry["gpu"]["status"] == "unavailable"
