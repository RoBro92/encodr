from __future__ import annotations

import pytest

from encodr_core.execution.backend_selection import select_execution_backend
from encodr_shared.worker_runtime import HardwareProbe

pytestmark = [pytest.mark.unit]


def test_intel_backend_uses_qsv_when_smoke_test_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        "encodr_core.execution.backend_selection.probe_execution_backends",
        lambda _path: [
            HardwareProbe(
                backend="intel_igpu",
                detected=True,
                usable=True,
                status="healthy",
                message="Intel QSV is available.",
                details={
                    "qsv": {"usable": True, "render_devices": ["/dev/dri/renderD128"]},
                    "vaapi": {"usable": True, "device_paths": [{"path": "/dev/dri/renderD128"}]},
                },
            )
        ],
    )

    selection = select_execution_backend(
        ffmpeg_path="ffmpeg",
        preferred_backend="prefer_intel_igpu",
        allow_cpu_fallback=True,
        target_codec="h264",
    )

    assert selection.accelerator == "qsv"
    assert selection.actual_backend == "intel_qsv"
    assert selection.video_encoder == "h264_qsv"
    assert selection.device_path == "/dev/dri/renderD128"
    assert selection.command_prefix == [
        "-init_hw_device",
        "vaapi=va:/dev/dri/renderD128",
        "-init_hw_device",
        "qsv=qs@va",
        "-filter_hw_device",
        "qs",
    ]


def test_intel_backend_falls_back_to_vaapi_when_qsv_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "encodr_core.execution.backend_selection.probe_execution_backends",
        lambda _path: [
            HardwareProbe(
                backend="intel_igpu",
                detected=True,
                usable=True,
                status="healthy",
                message="Intel VAAPI active; QSV unavailable: MFX session init failed",
                details={
                    "selected_backend": "intel_vaapi",
                    "qsv_unavailable_reason": "MFX session init failed",
                    "qsv": {
                        "usable": False,
                        "render_devices": ["/dev/dri/renderD128"],
                        "reason_unavailable": "MFX session init failed",
                    },
                    "vaapi": {"usable": True, "device_paths": [{"path": "/dev/dri/renderD128"}]},
                },
            )
        ],
    )

    selection = select_execution_backend(
        ffmpeg_path="ffmpeg",
        preferred_backend="prefer_intel_igpu",
        allow_cpu_fallback=True,
        target_codec="h264",
    )

    assert selection.accelerator == "vaapi"
    assert selection.actual_backend == "intel_vaapi"
    assert selection.video_encoder == "h264_vaapi"
    assert selection.device_path == "/dev/dri/renderD128"
    assert selection.selection_reason == "Using Intel iGPU / VAAPI for hardware-accelerated video encoding. QSV unavailable: MFX session init failed."
