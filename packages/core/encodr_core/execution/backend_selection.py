from __future__ import annotations

import os
from pathlib import Path

from encodr_core.config.base import ConfigModel
from encodr_shared.worker_runtime import probe_execution_backends


PREFERENCE_TO_BACKEND = {
    "cpu_only": "cpu",
    "prefer_intel_igpu": "intel_igpu",
    "prefer_nvidia_gpu": "nvidia_gpu",
    "prefer_amd_gpu": "amd_gpu",
    "cpu": "cpu",
    "intel_igpu": "intel_igpu",
    "nvidia_gpu": "nvidia_gpu",
    "amd_gpu": "amd_gpu",
}

CPU_ENCODERS = {
    "h264": "libx264",
    "hevc": "libx265",
    "av1": "libaom-av1",
}

NVENC_ENCODERS = {
    "h264": "h264_nvenc",
    "hevc": "hevc_nvenc",
}

QSV_ENCODERS = {
    "h264": "h264_qsv",
    "hevc": "hevc_qsv",
}

VAAPI_ENCODERS = {
    "h264": "h264_vaapi",
    "hevc": "hevc_vaapi",
}

AMF_ENCODERS = {
    "h264": "h264_amf",
    "hevc": "hevc_amf",
}

CPU_QUALITY_FLAGS = {
    "high_quality": ["-preset", "slow", "-crf", "18"],
    "balanced": ["-preset", "medium", "-crf", "20"],
    "efficient": ["-preset", "medium", "-crf", "23"],
}

NVENC_QUALITY_FLAGS = {
    "high_quality": ["-preset", "p5", "-rc", "vbr", "-cq", "19"],
    "balanced": ["-preset", "p4", "-rc", "vbr", "-cq", "21"],
    "efficient": ["-preset", "p3", "-rc", "vbr", "-cq", "24"],
}

QSV_QUALITY_FLAGS = {
    "high_quality": ["-global_quality", "19"],
    "balanced": ["-global_quality", "21"],
    "efficient": ["-global_quality", "24"],
}

VAAPI_QUALITY_FLAGS = {
    "high_quality": ["-qp", "19"],
    "balanced": ["-qp", "21"],
    "efficient": ["-qp", "24"],
}

AMF_QUALITY_FLAGS = {
    "high_quality": ["-quality", "quality", "-qp_i", "19", "-qp_p", "21"],
    "balanced": ["-quality", "balanced", "-qp_i", "21", "-qp_p", "23"],
    "efficient": ["-quality", "speed", "-qp_i", "24", "-qp_p", "26"],
}


class BackendSelectionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        requested_backend: str,
        allow_cpu_fallback: bool,
    ) -> None:
        self.requested_backend = requested_backend
        self.allow_cpu_fallback = allow_cpu_fallback
        super().__init__(message)


class SelectedExecutionBackend(ConfigModel):
    requested_backend: str
    actual_backend: str
    accelerator: str
    video_encoder: str
    command_prefix: list[str] = []
    video_filter: str | None = None
    quality_flags: list[str] = []
    fallback_used: bool = False
    selection_reason: str | None = None
    device_path: str | None = None


def normalise_backend_preference(value: str | None) -> str:
    cleaned = str(value or "cpu_only").strip()
    return PREFERENCE_TO_BACKEND.get(cleaned, "cpu")


def select_execution_backend(
    *,
    ffmpeg_path: Path | str,
    preferred_backend: str | None,
    allow_cpu_fallback: bool,
    target_codec: str | None,
) -> SelectedExecutionBackend:
    requested_backend = normalise_backend_preference(preferred_backend)
    codec = (target_codec or "hevc").strip().lower()

    if requested_backend == "cpu":
        return _cpu_selection(requested_backend=requested_backend, codec=codec)

    probes = {
        probe.backend: probe
        for probe in probe_execution_backends(ffmpeg_path)
    }
    requested_probe = probes.get(requested_backend)

    selection = _accelerated_selection(
        requested_backend=requested_backend,
        codec=codec,
        probe=requested_probe,
    )
    if selection is not None:
        return selection

    if allow_cpu_fallback:
        return _cpu_selection(
            requested_backend=requested_backend,
            codec=codec,
            fallback_used=True,
            selection_reason=(
                requested_probe.details.get("reason_unavailable") if requested_probe is not None else None
            )
            or f"Preferred backend '{requested_backend}' is unavailable, so Encodr is falling back to CPU execution.",
        )

    reason = (
        requested_probe.details.get("reason_unavailable")
        if requested_probe is not None
        else f"Preferred backend '{requested_backend}' is not supported."
    )
    raise BackendSelectionError(
        f"{reason} CPU fallback is disabled, so Encodr cannot execute this transcode safely.",
        requested_backend=requested_backend,
        allow_cpu_fallback=allow_cpu_fallback,
    )


def _cpu_selection(
    *,
    requested_backend: str,
    codec: str,
    fallback_used: bool = False,
    selection_reason: str | None = None,
) -> SelectedExecutionBackend:
    encoder = CPU_ENCODERS.get(codec)
    if encoder is None:
        raise BackendSelectionError(
            f"Codec '{codec}' is not supported by the CPU execution path.",
            requested_backend=requested_backend,
            allow_cpu_fallback=fallback_used or requested_backend == "cpu",
        )
    quality_mode = "high_quality"
    return SelectedExecutionBackend(
        requested_backend=requested_backend,
        actual_backend="cpu",
        accelerator="cpu",
        video_encoder=encoder,
        quality_flags=CPU_QUALITY_FLAGS[quality_mode],
        fallback_used=fallback_used,
        selection_reason=selection_reason,
    )


def quality_flags_for_backend(*, accelerator: str, quality_mode: str | None) -> list[str]:
    selected_mode = quality_mode or "high_quality"
    if accelerator == "cpu":
        return CPU_QUALITY_FLAGS.get(selected_mode, CPU_QUALITY_FLAGS["high_quality"])
    if accelerator == "nvenc":
        return NVENC_QUALITY_FLAGS.get(selected_mode, NVENC_QUALITY_FLAGS["high_quality"])
    if accelerator == "qsv":
        return QSV_QUALITY_FLAGS.get(selected_mode, QSV_QUALITY_FLAGS["high_quality"])
    if accelerator == "vaapi":
        return VAAPI_QUALITY_FLAGS.get(selected_mode, VAAPI_QUALITY_FLAGS["high_quality"])
    if accelerator == "amf":
        return AMF_QUALITY_FLAGS.get(selected_mode, AMF_QUALITY_FLAGS["high_quality"])
    return []


def _accelerated_selection(
    *,
    requested_backend: str,
    codec: str,
    probe,
) -> SelectedExecutionBackend | None:
    if probe is None or not probe.usable:
        return None

    if requested_backend == "intel_igpu":
        qsv = (probe.details.get("qsv") or {}) if isinstance(probe.details, dict) else {}
        vaapi = (probe.details.get("vaapi") or {}) if isinstance(probe.details, dict) else {}
        if qsv.get("usable"):
            encoder = QSV_ENCODERS.get(codec)
            if encoder is None:
                return None
            render_devices = qsv.get("render_devices") or []
            init_hw_device = "qsv=qsv"
            if render_devices and os.name != "nt":
                init_hw_device = f"qsv=qsv:{render_devices[0]}"
            return SelectedExecutionBackend(
                requested_backend=requested_backend,
                actual_backend="intel_igpu",
                accelerator="qsv",
                video_encoder=encoder,
                command_prefix=["-init_hw_device", init_hw_device, "-filter_hw_device", "qsv"],
                video_filter="format=nv12,hwupload=extra_hw_frames=64",
                selection_reason="Using Intel QSV for hardware-accelerated video encoding.",
                device_path=str(render_devices[0]) if render_devices else None,
            )
        if vaapi.get("usable"):
            encoder = VAAPI_ENCODERS.get(codec)
            if encoder is None:
                return None
            device_path = _first_device_path(vaapi)
            if device_path is None:
                return None
            qsv_reason = _probe_reason(qsv) or "QSV is unavailable in this runtime"
            return SelectedExecutionBackend(
                requested_backend=requested_backend,
                actual_backend="intel_igpu",
                accelerator="vaapi",
                video_encoder=encoder,
                command_prefix=["-vaapi_device", device_path],
                video_filter="format=nv12,hwupload",
                selection_reason=f"Using Intel VAAPI because QSV is unavailable: {qsv_reason}.",
                device_path=device_path,
            )
        return None

    if requested_backend == "nvidia_gpu":
        encoder = NVENC_ENCODERS.get(codec)
        if encoder is None:
            return None
        return SelectedExecutionBackend(
            requested_backend=requested_backend,
            actual_backend="nvidia_gpu",
            accelerator="nvenc",
            video_encoder=encoder,
            selection_reason="Using NVIDIA NVENC for hardware-accelerated video encoding.",
        )

    if requested_backend == "amd_gpu":
        amf = (probe.details.get("amf") or {}) if isinstance(probe.details, dict) else {}
        if amf.get("usable"):
            encoder = AMF_ENCODERS.get(codec)
            if encoder is None:
                return None
            return SelectedExecutionBackend(
                requested_backend=requested_backend,
                actual_backend="amd_gpu",
                accelerator="amf",
                video_encoder=encoder,
                selection_reason="Using AMD AMF for hardware-accelerated video encoding.",
            )
        vaapi = (probe.details.get("vaapi") or {}) if isinstance(probe.details, dict) else {}
        if vaapi.get("usable"):
            encoder = VAAPI_ENCODERS.get(codec)
            if encoder is None:
                return None
            device_path = _first_device_path(vaapi)
            if device_path is None:
                return None
            return SelectedExecutionBackend(
                requested_backend=requested_backend,
                actual_backend="amd_gpu",
                accelerator="vaapi",
                video_encoder=encoder,
                command_prefix=["-vaapi_device", device_path],
                video_filter="format=nv12,hwupload",
                selection_reason="Using AMD VAAPI for hardware-accelerated video encoding.",
                device_path=device_path,
            )
    return None


def _first_device_path(details: dict[str, object]) -> str | None:
    device_paths = details.get("device_paths") or []
    if not isinstance(device_paths, list):
        return None
    for item in device_paths:
        if isinstance(item, dict) and item.get("path"):
            return str(item["path"])
    return None


def _probe_reason(details: dict[str, object]) -> str | None:
    reason = details.get("reason_unavailable") or details.get("message")
    if isinstance(reason, str) and reason.strip():
        return reason.strip().rstrip(".")
    smoke_test = details.get("ffmpeg_smoke_test")
    if isinstance(smoke_test, dict):
        stderr = smoke_test.get("stderr")
        if isinstance(stderr, str) and stderr.strip():
            return stderr.strip().rstrip(".")
    return None
