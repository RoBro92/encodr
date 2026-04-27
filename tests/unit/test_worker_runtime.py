from __future__ import annotations

from pathlib import Path

import pytest

from encodr_shared.worker_runtime import (
    HardwareProbe,
    probe_device_node,
    probe_execution_backends,
    probe_intel_qsv,
    probe_intel_vaapi,
)


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
        "encodr_shared.worker_runtime.probe_intel_vaapi",
        lambda _path: HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=True,
            status="healthy",
            message="Intel VAAPI is available and validated in the current runtime.",
            details={"device_paths": [{"path": "/dev/dri/renderD128"}]},
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


def test_worker_image_includes_intel_vaapi_runtime_packages(repo_root: Path) -> None:
    dockerfile = (repo_root / "infra/docker/worker.Dockerfile").read_text(encoding="utf-8")

    for package_name in [
        "vainfo",
        "intel-media-va-driver",
        "libva2",
        "libva-drm2",
        "mesa-va-drivers",
    ]:
        assert package_name in dockerfile

    assert "intel-media-va-driver-non-free" not in dockerfile


def test_probe_intel_vaapi_reports_missing_vainfo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("encodr_shared.worker_runtime.detect_ffmpeg_hwaccels", lambda _path: ["vaapi"])
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
            }
        ],
    )
    monkeypatch.setattr("encodr_shared.worker_runtime.Path.exists", lambda self: str(self) == "/dev/dri")
    monkeypatch.setattr(
        "encodr_shared.worker_runtime._run_command_capture",
        lambda command, **kwargs: (1, "", "") if command == ["which", "vainfo"] else (0, "", ""),
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime._device_probe",
        lambda path: {
            "path": Path(path).as_posix(),
            "exists": True,
            "readable": True,
            "writable": True,
            "is_character_device": True,
            "status": "healthy",
            "message": "Device path is present and readable.",
        },
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_binary",
        lambda path: type(
            "BinaryProbe",
            (),
            {
                "configured_path": str(path),
                "resolved_path": None if str(path) == "vainfo" else "/usr/bin/ffmpeg",
                "exists": str(path) != "vainfo",
                "executable": str(path) != "vainfo",
                "discoverable": str(path) != "vainfo",
                "status": "failed" if str(path) == "vainfo" else "healthy",
                "message": "Binary is not discoverable or executable."
                if str(path) == "vainfo"
                else "Binary is discoverable and executable.",
            },
        )(),
    )

    probe = probe_intel_vaapi("ffmpeg")

    assert probe.usable is False
    assert probe.details["reason_unavailable"] == "vainfo missing"
    assert probe.details["vainfo"]["which"] == {
        "command": "which vainfo",
        "returncode": 1,
        "stdout": None,
        "stderr": None,
    }


def test_probe_intel_vaapi_reports_driver_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("encodr_shared.worker_runtime.detect_ffmpeg_hwaccels", lambda _path: ["vaapi"])
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
            }
        ],
    )
    monkeypatch.setattr("encodr_shared.worker_runtime.Path.exists", lambda self: str(self) == "/dev/dri")
    monkeypatch.setattr(
        "encodr_shared.worker_runtime._device_probe",
        lambda path: {
            "path": Path(path).as_posix(),
            "exists": True,
            "readable": True,
            "writable": True,
            "is_character_device": True,
            "status": "healthy",
            "message": "Device path is present and readable.",
        },
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_binary",
        lambda path: type(
            "BinaryProbe",
            (),
            {
                "configured_path": str(path),
                "resolved_path": f"/usr/bin/{path}",
                "exists": True,
                "executable": True,
                "discoverable": True,
                "status": "healthy",
                "message": "Binary is discoverable and executable.",
            },
        )(),
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime._run_command_capture",
        lambda command, **kwargs: (
            1,
            "",
            "libva error: /usr/lib/x86_64-linux-gnu/dri/iHD_drv_video.so init failed",
        )
        if "vainfo" in command[0]
        else (0, "", ""),
    )

    probe = probe_intel_vaapi("ffmpeg")

    assert probe.usable is False
    assert probe.details["reason_unavailable"] == "Intel driver missing"


def test_probe_intel_qsv_is_left_unverified_without_dedicated_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("encodr_shared.worker_runtime.detect_ffmpeg_hwaccels", lambda _path: ["qsv", "vaapi"])
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.Path.glob",
        lambda self, pattern: [Path("/dev/dri/renderD128")] if str(self) == "/dev/dri" and pattern == "renderD*" else [],
    )

    probe = probe_intel_qsv("ffmpeg")

    assert probe.detected is True
    assert probe.usable is False
    assert probe.status == "unknown"
