from __future__ import annotations

import logging

import pytest

from encodr_core.execution.backend_selection import BackendSelectionError, select_execution_backend
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
        "qsv=qs:hw,child_device=/dev/dri/renderD128",
        "-filter_hw_device",
        "qs",
    ]


def test_intel_backend_falls_back_to_vaapi_when_qsv_fails(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO, logger="encodr.execution.backend")
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
    fallback_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "backend_fallback"
    )
    selected_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "backend_selected"
    )
    assert fallback_record.levelno == logging.WARNING
    assert getattr(fallback_record, "attempted_backend", None) == "intel_qsv"
    assert getattr(fallback_record, "selected_backend", None) == "intel_vaapi"
    assert "MFX session init failed" in str(getattr(fallback_record, "fallback_reason", ""))
    assert selected_record.levelno == logging.INFO
    assert getattr(selected_record, "actual_backend", None) == "intel_vaapi"


def test_intel_auto_falls_back_to_cpu_when_hardware_fails_and_cpu_allowed(monkeypatch) -> None:
    monkeypatch.setattr(
        "encodr_core.execution.backend_selection.probe_execution_backends",
        lambda _path: [
            HardwareProbe(
                backend="intel_igpu",
                detected=True,
                usable=False,
                status="failed",
                message="Intel hardware is unavailable.",
                details={
                    "qsv": {"usable": False, "reason_unavailable": "MFX session init failed"},
                    "vaapi": {"usable": False, "reason_unavailable": "VAAPI init failed"},
                },
            )
        ],
    )

    selection = select_execution_backend(
        ffmpeg_path="ffmpeg",
        preferred_backend="intel_auto",
        allow_cpu_fallback=True,
        target_codec="h264",
    )

    assert selection.actual_backend == "cpu"
    assert selection.fallback_used is True
    assert "QSV unavailable: MFX session init failed" in str(selection.selection_reason)
    assert "VAAPI unavailable: VAAPI init failed" in str(selection.selection_reason)


def test_qsv_mode_requires_qsv_when_fallback_disabled(monkeypatch) -> None:
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
                    "qsv": {"usable": False, "reason_unavailable": "MFX session init failed"},
                    "vaapi": {"usable": True, "device_paths": [{"path": "/dev/dri/renderD128"}]},
                },
            )
        ],
    )

    with pytest.raises(BackendSelectionError, match="MFX session init failed"):
        select_execution_backend(
            ffmpeg_path="ffmpeg",
            preferred_backend="intel_qsv",
            allow_cpu_fallback=False,
            target_codec="h264",
        )


def test_vaapi_mode_ignores_failed_qsv_when_vaapi_passes(monkeypatch) -> None:
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
                    "qsv": {"usable": False, "reason_unavailable": "MFX session init failed"},
                    "vaapi": {"usable": True, "device_paths": [{"path": "/dev/dri/renderD128"}]},
                },
            )
        ],
    )

    selection = select_execution_backend(
        ffmpeg_path="ffmpeg",
        preferred_backend="intel_vaapi",
        allow_cpu_fallback=False,
        target_codec="h264",
    )

    assert selection.actual_backend == "intel_vaapi"
    assert selection.accelerator == "vaapi"
    assert selection.fallback_used is False
