from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from encodr_shared import (
    backend_preference_label,
    coerce_backend_preference,
    hardware_hints_from_backend_probes,
)
from encodr_shared.worker_runtime import (
    BinaryProbe,
    HardwareProbe,
    probe_device_node,
    probe_execution_backends,
    probe_intel_qsv,
    probe_intel_vaapi,
    resolve_backend_runtime_status,
    serialise_backend_probe,
    serialise_binary_probe,
)


pytestmark = [pytest.mark.unit]


def test_backend_preference_aliases_labels_and_hints_are_shared() -> None:
    assert coerce_backend_preference("cpu") == "cpu_only"
    assert coerce_backend_preference("nvidia_gpu") == "prefer_nvidia_gpu"
    assert coerce_backend_preference("auto") == "intel_auto"
    assert coerce_backend_preference("not-a-backend") == "cpu_only"
    assert backend_preference_label("intel_qsv") == "Intel QSV"

    hints = hardware_hints_from_backend_probes(
        [
            {
                "backend": "intel_igpu",
                "usable_by_ffmpeg": True,
                "details": {"usable_backends": ["intel_qsv", "intel_vaapi"]},
            },
            {"backend": "cpu", "usable_by_ffmpeg": True, "details": {}},
        ]
    )

    assert hints == ["intel_igpu", "intel_qsv", "intel_vaapi"]


def test_worker_runtime_serialisation_golden_payloads() -> None:
    backend_payload = serialise_backend_probe(
        HardwareProbe(
            backend="intel_igpu",
            detected=True,
            usable=False,
            status="failed",
            message="Intel iGPU passthrough is not fully usable in this runtime.",
            details={
                "ffmpeg_path_verified": False,
                "reason_unavailable": "permission denied",
                "recommended_usage": "Expose /dev/dri to the worker runtime.",
                "device_paths": [{"path": "/dev/dri/renderD128", "status": "failed"}],
                "nested": {"state": "kept"},
            },
        )
    )

    assert backend_payload == {
        "backend": "intel_igpu",
        "preference_key": "prefer_intel_igpu",
        "preference_keys": ["prefer_intel_igpu", "intel_auto", "intel_qsv", "intel_vaapi", "qsv", "vaapi", "auto"],
        "detected": True,
        "usable_by_ffmpeg": False,
        "ffmpeg_path_verified": False,
        "status": "failed",
        "message": "Intel iGPU passthrough is not fully usable in this runtime.",
        "reason_unavailable": "permission denied",
        "recommended_usage": "Expose /dev/dri to the worker runtime.",
        "selected_backend": None,
        "usable_backends": [],
        "fallback_reason": None,
        "qsv_unavailable_reason": None,
        "device_paths": [{"path": "/dev/dri/renderD128", "status": "failed"}],
        "details": {
            "ffmpeg_path_verified": False,
            "reason_unavailable": "permission denied",
            "recommended_usage": "Expose /dev/dri to the worker runtime.",
            "device_paths": [{"path": "/dev/dri/renderD128", "status": "failed"}],
            "nested": {"state": "kept"},
        },
    }

    binary_payload = serialise_binary_probe(
        BinaryProbe(
            configured_path="vainfo",
            resolved_path="/usr/bin/vainfo",
            exists=True,
            executable=True,
            discoverable=True,
            status="healthy",
            message="Binary is discoverable and executable.",
        ),
        name="vainfo",
        which_payload={"command": "which vainfo", "returncode": 0, "stdout": "/usr/bin/vainfo", "stderr": None},
    )

    assert binary_payload == {
        "name": "vainfo",
        "configured_path": "vainfo",
        "resolved_path": "/usr/bin/vainfo",
        "exists": True,
        "executable": True,
        "discoverable": True,
        "status": "healthy",
        "message": "Binary is discoverable and executable.",
        "which": {"command": "which vainfo", "returncode": 0, "stdout": "/usr/bin/vainfo", "stderr": None},
    }


def test_probe_device_node_reports_owner_group_mode_and_readability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_exists = Path.exists
    real_stat = Path.stat

    monkeypatch.setattr(
        "encodr_shared.worker_runtime.Path.exists",
        lambda self: self.as_posix() == "/dev/dri/renderD128" or real_exists(self),
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.Path.is_char_device",
        lambda self: self.as_posix() == "/dev/dri/renderD128",
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.os.access",
        lambda path, mode: Path(path).as_posix() == "/dev/dri/renderD128",
    )

    def fake_stat(self: Path) -> SimpleNamespace:
        if self.as_posix() == "/dev/dri/renderD128":
            return SimpleNamespace(st_uid=0, st_gid=993, st_mode=0o20660)
        return real_stat(self)

    monkeypatch.setattr("encodr_shared.worker_runtime.Path.stat", fake_stat)

    payload = probe_device_node("/dev/dri/renderD128")

    assert payload["uid"] == 0
    assert payload["gid"] == 993
    assert payload["mode"] == "0660"
    assert payload["readable"] is True
    assert payload["status"] == "healthy"


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
    agent_dockerfile = (repo_root / "infra/docker/worker-agent.Dockerfile").read_text(encoding="utf-8")

    for package_name in [
        "vainfo",
        "intel-media-va-driver",
        "libva2",
        "libva-drm2",
        "mesa-va-drivers",
        "libvpl2",
    ]:
        assert package_name in dockerfile
        assert package_name in agent_dockerfile

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


def test_probe_intel_qsv_reports_mfx_session_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("encodr_shared.worker_runtime.detect_ffmpeg_hwaccels", lambda _path: ["qsv", "vaapi"])
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
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_binary",
        lambda path: type(
            "BinaryProbe",
            (),
            {
                "configured_path": str(path),
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
        "encodr_shared.worker_runtime._run_command_capture",
        lambda command, **kwargs: (1, "", "Error creating a MFX session: -9"),
    )

    probe = probe_intel_qsv("ffmpeg")

    assert probe.detected is True
    assert probe.usable is False
    assert probe.status == "failed"
    assert probe.details["reason_unavailable"] == "MFX session init failed"


def test_probe_intel_qsv_validates_smoke_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("encodr_shared.worker_runtime.detect_ffmpeg_hwaccels", lambda _path: ["qsv", "vaapi"])
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
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_binary",
        lambda path: type(
            "BinaryProbe",
            (),
            {
                "configured_path": str(path),
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
        "encodr_shared.worker_runtime._run_command_capture",
        lambda command, **kwargs: (0, "", ""),
    )

    probe = probe_intel_qsv("ffmpeg")

    assert probe.detected is True
    assert probe.usable is True
    assert probe.status == "healthy"
    assert probe.details["validation_state"] == "usable"


def test_probe_execution_backends_keeps_worker_healthy_when_qsv_fails_and_vaapi_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr("encodr_shared.worker_runtime.detect_ffmpeg_hwaccels", lambda _path: ["qsv", "vaapi"])
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
        ],
    )
    monkeypatch.setattr(
        "encodr_shared.worker_runtime.probe_intel_qsv",
        lambda _path: HardwareProbe(
            backend="intel_qsv",
            detected=True,
            usable=False,
            status="failed",
            message="Intel QSV is visible, but FFmpeg could not create an MFX session.",
            details={"reason_unavailable": "MFX session init failed", "render_devices": ["/dev/dri/renderD128"]},
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

    intel_probe = next(item for item in probe_execution_backends("ffmpeg") if item.backend == "intel_igpu")

    assert intel_probe.usable is True
    assert intel_probe.status == "healthy"
    assert intel_probe.details["selected_backend"] == "intel_vaapi"
    assert intel_probe.details["usable_backends"] == ["intel_vaapi"]
    assert intel_probe.details["fallback_reason"] is None
    assert intel_probe.details["qsv_unavailable_reason"] == "MFX session init failed"
    assert intel_probe.message == "Intel VAAPI active; QSV unavailable: MFX session init failed"


def test_runtime_status_selects_vaapi_when_qsv_fails_and_vaapi_passes() -> None:
    status = resolve_backend_runtime_status(
        "intel_auto",
        [
            {
                "backend": "intel_igpu",
                "preference_key": "prefer_intel_igpu",
                "preference_keys": ["prefer_intel_igpu", "intel_auto", "intel_qsv", "intel_vaapi"],
                "usable_by_ffmpeg": True,
                "message": "Intel VAAPI active; QSV unavailable: MFX session init failed",
                "details": {
                    "qsv": {"usable": False, "reason_unavailable": "MFX session init failed"},
                    "vaapi": {"usable": True},
                    "qsv_unavailable_reason": "MFX session init failed",
                },
            }
        ],
        allow_cpu_fallback=True,
        cpu_available=True,
    )

    assert status["selected_backend"] == "intel_vaapi"
    assert status["transcode_backend_usable"] is True
    assert status["degraded"] is False
    assert status["qsv_unavailable_reason"] == "MFX session init failed"


def test_runtime_status_selects_cpu_when_intel_hardware_fails_and_fallback_allowed() -> None:
    status = resolve_backend_runtime_status(
        "intel_auto",
        [
            {
                "backend": "intel_igpu",
                "preference_key": "prefer_intel_igpu",
                "preference_keys": ["prefer_intel_igpu", "intel_auto", "intel_qsv", "intel_vaapi"],
                "usable_by_ffmpeg": False,
                "message": "Intel hardware unavailable.",
                "details": {
                    "qsv": {"usable": False, "reason_unavailable": "MFX session init failed"},
                    "vaapi": {"usable": False, "reason_unavailable": "VAAPI init failed"},
                },
            }
        ],
        allow_cpu_fallback=True,
        cpu_available=True,
    )

    assert status["selected_backend"] == "cpu"
    assert status["transcode_backend_usable"] is True
    assert status["degraded"] is False
    assert "QSV unavailable: MFX session init failed" in str(status["fallback_reason"])


def test_runtime_status_degrades_when_qsv_is_required_and_fails() -> None:
    status = resolve_backend_runtime_status(
        "intel_qsv",
        [
            {
                "backend": "intel_igpu",
                "preference_key": "prefer_intel_igpu",
                "preference_keys": ["prefer_intel_igpu", "intel_auto", "intel_qsv", "intel_vaapi"],
                "usable_by_ffmpeg": True,
                "message": "Intel VAAPI active; QSV unavailable: MFX session init failed",
                "details": {
                    "qsv": {"usable": False, "reason_unavailable": "MFX session init failed"},
                    "vaapi": {"usable": True},
                },
            }
        ],
        allow_cpu_fallback=True,
        cpu_available=True,
    )

    assert status["selected_backend"] == "cpu"
    assert status["transcode_backend_usable"] is True
    assert status["degraded"] is True
