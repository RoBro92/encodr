from __future__ import annotations

from pathlib import Path

import pytest

from encodr_shared.worker_runtime import HardwareProbe, probe_execution_backends, probe_device_node


pytestmark = [pytest.mark.unit]


def test_probe_execution_backends_reports_cpu_and_detected_gpu_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_binary",
        lambda _path: type(
            "BinaryProbe",
            (),
            {
                "configured_path": "ffmpeg",
                "resolved_path": "/usr/bin/ffmpeg",
                "exists": True,
                "executable": True,
                "discoverable": True,
                "status": "healthy",
                "message": "Binary is discoverable and executable.",
            },
        )(),
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.detect_ffmpeg_hwaccels",
        lambda _path: ["qsv", "vaapi", "cuda"],
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.discover_runtime_devices",
        lambda: [
            {
                "path": "/dev/dri/renderD128",
                "exists": True,
                "readable": True,
                "writable": True,
                "is_character_device": True,
                "status": "healthy",
                "message": "Device path is present and readable.",
                "vendor_id": "0x8086",
                "vendor_name": "Intel",
            },
            {
                "path": "/dev/nvidia0",
                "exists": True,
                "readable": True,
                "writable": True,
                "is_character_device": True,
                "status": "healthy",
                "message": "Device path is present and readable.",
                "vendor_id": "0x10de",
                "vendor_name": "NVIDIA",
            },
        ],
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_intel_qsv",
        lambda _path: HardwareProbe(
            backend="intel_qsv",
            detected=True,
            usable=True,
            status="healthy",
            message="Intel QSV is available and FFmpeg can initialise it.",
            details={},
        ),
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_vaapi",
        lambda _path, *, device_path: HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=device_path == Path("/dev/dri/renderD128"),
            status="healthy" if device_path == Path("/dev/dri/renderD128") else "failed",
            message="VAAPI ok" if device_path == Path("/dev/dri/renderD128") else "VAAPI unavailable",
            details={"device_paths": [{"path": str(device_path)}]},
        ),
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_nvenc",
        lambda _path: HardwareProbe(
            backend="nvidia_gpu",
            detected=True,
            usable=True,
            status="healthy",
            message="NVIDIA hardware encoding is available and FFmpeg can initialise it.",
            details={"device_paths": [{"path": "/dev/nvidia0"}]},
        ),
    )

    backends = probe_execution_backends("ffmpeg")

    assert [item.backend for item in backends] == ["cpu", "intel_igpu", "nvidia_gpu", "amd_gpu"]
    assert backends[0].usable is True
    assert backends[1].usable is True
    assert backends[2].usable is True
    assert backends[3].usable is False


def test_probe_device_node_reports_missing_path() -> None:
    result = probe_device_node("/definitely/missing/device")

    assert result["exists"] is False
    assert result["status"] == "failed"
    assert result["message"] == "Device path is not present."
