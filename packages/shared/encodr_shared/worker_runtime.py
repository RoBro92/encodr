from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shlex
import shutil
import subprocess
from typing import Any


@dataclass(frozen=True, slots=True)
class BinaryProbe:
    configured_path: str
    resolved_path: str | None
    exists: bool
    executable: bool
    discoverable: bool
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class HardwareProbe:
    backend: str
    detected: bool
    usable: bool
    status: str
    message: str
    details: dict[str, object]


def _read_text_if_present(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _device_probe(path: Path) -> dict[str, object]:
    exists = path.exists()
    readable = os.access(path, os.R_OK) if exists else False
    writable = os.access(path, os.W_OK) if exists else False
    is_char_device = False
    if exists:
        try:
            is_char_device = path.is_char_device()
        except OSError:
            is_char_device = False

    if not exists:
        status = "failed"
        message = "Device path is not present."
    elif not is_char_device:
        status = "failed"
        message = "Path exists but is not a character device."
    elif not readable:
        status = "failed"
        message = "Device path exists but is not readable."
    else:
        status = "healthy"
        message = "Device path is present and readable."

    return {
        "path": path.as_posix(),
        "exists": exists,
        "readable": readable,
        "writable": writable,
        "is_character_device": is_char_device,
        "status": status,
        "message": message,
    }


def probe_device_node(path: Path | str) -> dict[str, object]:
    return _device_probe(Path(path))


def discover_runtime_devices() -> list[dict[str, object]]:
    device_entries: list[dict[str, object]] = []
    seen: set[str] = set()

    def add_device(path: Path, *, vendor_id: str | None = None, vendor_name: str | None = None) -> None:
        text_path = path.as_posix()
        if text_path in seen:
            return
        seen.add(text_path)
        entry = _device_probe(path)
        resolved_vendor_id = vendor_id
        resolved_vendor_name = vendor_name
        if text_path.startswith("/dev/dri/"):
            sysfs_vendor = _read_text_if_present(Path("/sys/class/drm") / path.name / "device" / "vendor")
            resolved_vendor_id = sysfs_vendor or vendor_id
            resolved_vendor_name = vendor_name_from_id(resolved_vendor_id) or vendor_name
        entry["vendor_id"] = resolved_vendor_id
        entry["vendor_name"] = resolved_vendor_name
        device_entries.append(entry)

    dri_root = Path("/dev/dri")
    add_device(Path("/dev/dri/renderD128"))
    add_device(Path("/dev/dri/card0"))
    if dri_root.exists():
        for device_path in sorted(dri_root.glob("renderD*")) + sorted(dri_root.glob("card*")):
            add_device(device_path)

    nvidia_paths = [Path("/dev/nvidiactl"), Path("/dev/nvidia-uvm"), *sorted(Path("/dev").glob("nvidia[0-9]*"))]
    for device_path in nvidia_paths:
        add_device(device_path, vendor_id="0x10de", vendor_name="NVIDIA")

    return device_entries


def vendor_name_from_id(vendor_id: str | None) -> str | None:
    cleaned = (vendor_id or "").strip().lower()
    if cleaned in {"0x8086", "8086"}:
        return "Intel"
    if cleaned in {"0x1002", "1002"}:
        return "AMD"
    if cleaned in {"0x10de", "10de"}:
        return "NVIDIA"
    return None


def _run_ffmpeg_probe(command: list[str], *, timeout: int = 10) -> tuple[bool, str | None]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if completed.returncode == 0:
        return True, None
    stderr = (completed.stderr or completed.stdout or "").strip()
    return False, stderr[:1000] if stderr else "FFmpeg hardware probe failed."


def _run_command_capture(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 10,
) -> tuple[int | None, str, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, "", str(error)
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def probe_which(binary_name: str) -> dict[str, object]:
    command = ["where", binary_name] if os.name == "nt" else ["which", binary_name]
    returncode, stdout, stderr = _run_command_capture(command, timeout=5)
    return {
        "command": " ".join(shlex.quote(part) for part in command),
        "returncode": returncode,
        "stdout": stdout.strip() or None,
        "stderr": stderr.strip() or None,
    }


def _run_text_command(command: list[str], *, timeout: int = 10) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def probe_windows_video_adapters() -> list[str]:
    if os.name != "nt":
        return []
    candidates = [
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty AdapterCompatibility",
        ],
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-WmiObject Win32_VideoController | Select-Object -ExpandProperty AdapterCompatibility",
        ],
    ]
    values: list[str] = []
    for command in candidates:
        output = _run_text_command(command)
        if not output:
            continue
        for line in output.splitlines():
            cleaned = line.strip()
            if cleaned and cleaned not in values:
                values.append(cleaned)
        if values:
            break
    return values


def probe_vaapi(ffmpeg_path: Path | str, *, device_path: Path | str) -> HardwareProbe:
    hwaccels = detect_ffmpeg_hwaccels(ffmpeg_path)
    device = Path(device_path)
    device_probe = _device_probe(device)
    if not device_probe["exists"]:
        return HardwareProbe(
            backend="vaapi",
            detected=False,
            usable=False,
            status="failed",
            message="No VAAPI render device is visible to the runtime.",
            details={"hwaccels": hwaccels, "device_paths": [device_probe]},
        )
    if "vaapi" not in hwaccels:
        return HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=False,
            status="failed",
            message="FFmpeg does not report VAAPI hardware acceleration support.",
            details={"hwaccels": hwaccels, "device_paths": [device_probe]},
        )

    resolved_ffmpeg = probe_binary(ffmpeg_path).resolved_path or str(ffmpeg_path)
    usable, error = _run_ffmpeg_probe(
        [
            resolved_ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-vaapi_device",
            device.as_posix(),
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=16x16:rate=1",
            "-frames:v",
            "1",
            "-vf",
            "format=nv12,hwupload",
            "-c:v",
            "hevc_vaapi",
            "-f",
            "null",
            "-",
        ]
    )
    return HardwareProbe(
        backend="vaapi",
        detected=True,
        usable=usable,
        status="healthy" if usable else "failed",
        message=(
            "VAAPI is available and FFmpeg can initialise it."
            if usable
            else "VAAPI device is visible but FFmpeg could not initialise it."
        ),
        details={
            "hwaccels": hwaccels,
            "device_paths": [device_probe],
            "stderr": error,
        },
    )


def _device_probe_from_path(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    return _device_probe(path)


def _classify_intel_vaapi_failure(stderr: str) -> tuple[str, str]:
    lowered = stderr.lower()
    if "permission denied" in lowered:
        return "permission denied", "Permission denied while accessing the Intel render device."
    if "command not found" in lowered or "no such file or directory" in lowered:
        return "vainfo missing", "Intel VAAPI validation cannot run because vainfo is not installed."
    if (
        "driver not found" in lowered
        or "failed to open" in lowered
        or "failed to initialize display" in lowered
        or "init failed" in lowered
        or "dlopen" in lowered
        or "ihd_drv_video" in lowered
    ):
        return "Intel driver missing", "Intel VAAPI userspace driver is missing or could not be loaded."
    if "vaapi" in lowered or "libva" in lowered:
        return "VAAPI init failed", "Intel VAAPI initialisation failed in the current runtime."
    return "VAAPI init failed", "Intel VAAPI initialisation failed in the current runtime."


def probe_intel_vaapi(ffmpeg_path: Path | str) -> HardwareProbe:
    hwaccels = detect_ffmpeg_hwaccels(ffmpeg_path)
    dri_root = Path("/dev/dri")
    render_device = next(
        (
            Path(item["path"])
            for item in discover_runtime_devices()
            if item.get("vendor_name") == "Intel" and str(item.get("path", "")).startswith("/dev/dri/renderD")
        ),
        None,
    )
    card_device = next(
        (
            Path(item["path"])
            for item in discover_runtime_devices()
            if item.get("vendor_name") == "Intel" and str(item.get("path", "")).startswith("/dev/dri/card")
        ),
        None,
    )
    dri_visible = dri_root.exists()
    render_probe = _device_probe_from_path(render_device)
    card_probe = _device_probe_from_path(card_device)
    device_paths = [item for item in [render_probe, card_probe] if item is not None]

    base_details: dict[str, Any] = {
        "hwaccels": hwaccels,
        "device_paths": device_paths,
        "dri_root_visible": dri_visible,
        "render_node": render_probe,
        "card_node": card_probe,
        "driver_name": "iHD",
    }

    if not dri_visible:
        return HardwareProbe(
            backend="vaapi",
            detected=False,
            usable=False,
            status="failed",
            message="Intel VAAPI is unavailable because /dev/dri is not visible in the runtime.",
            details=base_details
            | {
                "validation_state": "device missing",
                "reason_unavailable": "device missing",
                "recommended_usage": "Expose /dev/dri from the LXC or VM into the worker container before selecting Intel iGPU.",
            },
        )

    if render_probe is None or not render_probe["exists"]:
        return HardwareProbe(
            backend="vaapi",
            detected=False,
            usable=False,
            status="failed",
            message="Intel VAAPI is unavailable because no Intel render node is visible in the runtime.",
            details=base_details
            | {
                "validation_state": "device missing",
                "reason_unavailable": "device missing",
                "recommended_usage": "Expose the Intel render node, such as /dev/dri/renderD128, to the worker container.",
            },
        )

    if not render_probe["readable"]:
        return HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=False,
            status="failed",
            message="Intel VAAPI is unavailable because the render node is present but not readable.",
            details=base_details
            | {
                "validation_state": "permission denied",
                "reason_unavailable": "permission denied",
                "recommended_usage": "Grant the worker container permission to read the Intel render node before enabling Intel iGPU.",
            },
        )

    vainfo_which = probe_which("vainfo")
    vainfo_probe = probe_binary("vainfo")
    vainfo_details = {
        "configured_path": vainfo_probe.configured_path,
        "resolved_path": vainfo_probe.resolved_path,
        "discoverable": vainfo_probe.discoverable,
        "message": vainfo_probe.message,
        "which": vainfo_which,
    }
    if not vainfo_probe.discoverable:
        return HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=False,
            status="failed",
            message="Intel VAAPI runtime validation cannot run because vainfo is not installed.",
            details=base_details
            | {
                "vainfo": vainfo_details,
                "validation_state": "vainfo missing",
                "reason_unavailable": "vainfo missing",
                "recommended_usage": "Install vainfo plus the Intel VAAPI runtime packages in the worker image.",
            },
        )

    vainfo_command = [
        vainfo_probe.resolved_path or "vainfo",
        "--display",
        "drm",
        "--device",
        render_device.as_posix(),
    ]
    vainfo_returncode, vainfo_stdout, vainfo_stderr = _run_command_capture(
        vainfo_command,
        env={"LIBVA_DRIVER_NAME": "iHD"},
        timeout=10,
    )
    vainfo_payload = vainfo_details | {
        "command": "LIBVA_DRIVER_NAME=iHD " + " ".join(vainfo_command),
        "returncode": vainfo_returncode,
        "stdout": vainfo_stdout.strip()[:1000] if vainfo_stdout else None,
        "stderr": vainfo_stderr.strip()[:1000] if vainfo_stderr else None,
    }
    if vainfo_returncode != 0:
        reason, message = _classify_intel_vaapi_failure(vainfo_stderr or vainfo_stdout)
        return HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=False,
            status="failed",
            message=message,
            details=base_details
            | {
                "vainfo": vainfo_payload,
                "validation_state": reason,
                "reason_unavailable": reason,
                "recommended_usage": "Validate Intel VAAPI with LIBVA_DRIVER_NAME=iHD vainfo against the render node inside the worker runtime.",
            },
        )

    resolved_ffmpeg = probe_binary(ffmpeg_path).resolved_path or str(ffmpeg_path)
    ffmpeg_command = [
        resolved_ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-vaapi_device",
        render_device.as_posix(),
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=1280x720:rate=30",
        "-t",
        "3",
        "-vf",
        "format=nv12,hwupload",
        "-c:v",
        "h264_vaapi",
        "-f",
        "null",
        "-",
    ]
    ffmpeg_returncode, ffmpeg_stdout, ffmpeg_stderr = _run_command_capture(
        ffmpeg_command,
        env={"LIBVA_DRIVER_NAME": "iHD"},
        timeout=20,
    )
    ffmpeg_payload = {
        "command": "LIBVA_DRIVER_NAME=iHD " + " ".join(ffmpeg_command),
        "returncode": ffmpeg_returncode,
        "stdout": ffmpeg_stdout.strip()[:1000] if ffmpeg_stdout else None,
        "stderr": ffmpeg_stderr.strip()[:1000] if ffmpeg_stderr else None,
    }
    if ffmpeg_returncode != 0:
        return HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=False,
            status="failed",
            message="Intel VAAPI initialised, but the FFmpeg VAAPI encode smoke test failed.",
            details=base_details
            | {
                "vainfo": vainfo_payload,
                "ffmpeg_smoke_test": ffmpeg_payload,
                "validation_state": "ffmpeg VAAPI encode test failed",
                "reason_unavailable": "ffmpeg VAAPI encode test failed",
                "recommended_usage": "Check the worker FFmpeg VAAPI path with a short h264_vaapi smoke test against the Intel render node.",
            },
        )

    return HardwareProbe(
        backend="vaapi",
        detected=True,
        usable=True,
        status="healthy",
        message="Intel VAAPI is available and validated in the current runtime.",
        details=base_details
        | {
            "vainfo": vainfo_payload,
            "ffmpeg_smoke_test": ffmpeg_payload,
            "ffmpeg_path_verified": True,
            "reason_unavailable": None,
            "recommended_usage": "Intel VAAPI is ready to use in this worker runtime.",
            "validation_state": "usable",
        },
    )


def probe_nvenc(ffmpeg_path: Path | str) -> HardwareProbe:
    hwaccels = detect_ffmpeg_hwaccels(ffmpeg_path)
    windows_adapters = probe_windows_video_adapters()
    device_paths = [
        _device_probe(Path("/dev/nvidiactl")),
        *[_device_probe(path) for path in sorted(Path("/dev").glob("nvidia[0-9]*"))],
    ]
    visible_devices = [item for item in device_paths if item["exists"]]
    detected = bool(visible_devices) or any("nvidia" in item.lower() for item in windows_adapters)
    if not visible_devices:
        if os.name != "nt" or not detected:
            return HardwareProbe(
                backend="nvidia_gpu",
                detected=False,
                usable=False,
                status="failed",
                message="No NVIDIA runtime device is visible to the runtime.",
                details={"hwaccels": hwaccels, "device_paths": device_paths, "windows_adapters": windows_adapters},
            )

    resolved_ffmpeg = probe_binary(ffmpeg_path).resolved_path or str(ffmpeg_path)
    usable, error = _run_ffmpeg_probe(
        [
            resolved_ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=16x16:rate=1",
            "-frames:v",
            "1",
            "-c:v",
            "h264_nvenc",
            "-f",
            "null",
            "-",
        ]
    )
    return HardwareProbe(
        backend="nvidia_gpu",
        detected=detected or usable,
        usable=usable,
        status="healthy" if usable else "failed",
        message=(
            "NVIDIA hardware encoding is available and FFmpeg can initialise it."
            if usable
            else "NVIDIA devices are visible but FFmpeg could not initialise NVENC."
        ),
        details={
            "hwaccels": hwaccels,
            "device_paths": device_paths,
            "windows_adapters": windows_adapters,
            "stderr": error,
        },
    )


def probe_amf(ffmpeg_path: Path | str) -> HardwareProbe:
    hwaccels = detect_ffmpeg_hwaccels(ffmpeg_path)
    windows_adapters = probe_windows_video_adapters()
    detected = any("amd" in item.lower() or "advanced micro devices" in item.lower() for item in windows_adapters)
    if os.name != "nt" and not detected:
        return HardwareProbe(
            backend="amd_gpu",
            detected=False,
            usable=False,
            status="failed",
            message="AMD AMF is only available on supported Windows runtimes.",
            details={"hwaccels": hwaccels, "windows_adapters": windows_adapters},
        )

    resolved_ffmpeg = probe_binary(ffmpeg_path).resolved_path or str(ffmpeg_path)
    usable, error = _run_ffmpeg_probe(
        [
            resolved_ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=16x16:rate=1",
            "-frames:v",
            "1",
            "-c:v",
            "h264_amf",
            "-f",
            "null",
            "-",
        ]
    )
    return HardwareProbe(
        backend="amd_gpu",
        detected=detected or usable,
        usable=usable,
        status="healthy" if usable else "failed",
        message=(
            "AMD AMF is available and FFmpeg can initialise it."
            if usable
            else "AMD hardware acceleration is visible but FFmpeg could not initialise AMF."
        ),
        details={
            "hwaccels": hwaccels,
            "windows_adapters": windows_adapters,
            "stderr": error,
        },
    )


def probe_execution_backends(ffmpeg_path: Path | str) -> list[HardwareProbe]:
    ffmpeg_probe = probe_binary(ffmpeg_path)
    all_devices = discover_runtime_devices()
    hwaccels = detect_ffmpeg_hwaccels(ffmpeg_path) if ffmpeg_probe.discoverable else []
    windows_adapters = probe_windows_video_adapters()

    cpu_probe = HardwareProbe(
        backend="cpu",
        detected=True,
        usable=ffmpeg_probe.discoverable,
        status="healthy" if ffmpeg_probe.discoverable else "failed",
        message=(
            "CPU execution is available."
            if ffmpeg_probe.discoverable
            else "CPU execution is unavailable because FFmpeg is not discoverable."
        ),
        details={
            "device_paths": [],
            "ffmpeg_hwaccels": hwaccels,
            "ffmpeg_path_verified": ffmpeg_probe.discoverable,
            "reason_unavailable": None if ffmpeg_probe.discoverable else ffmpeg_probe.message,
            "recommended_usage": "Use CPU execution as the safe fallback on any host.",
        },
    )

    intel_render = next(
        (
            Path(item["path"])
            for item in all_devices
            if item.get("vendor_name") == "Intel" and item["path"].startswith("/dev/dri/renderD")
        ),
        None,
    )
    intel_card = next(
        (
            Path(item["path"])
            for item in all_devices
            if item.get("vendor_name") == "Intel" and item["path"].startswith("/dev/dri/card")
        ),
        None,
    )
    amd_render = next(
        (
            Path(item["path"])
            for item in all_devices
            if item.get("vendor_name") == "AMD" and item["path"].startswith("/dev/dri/renderD")
        ),
        None,
    )

    qsv_probe = probe_intel_qsv(ffmpeg_path) if ffmpeg_probe.discoverable else HardwareProbe(
        backend="intel_qsv",
        detected=False,
        usable=False,
        status="failed",
        message="FFmpeg is not discoverable, so Intel QSV cannot be tested.",
        details={"device_paths": [], "hwaccels": hwaccels},
    )
    intel_vaapi_probe = probe_intel_vaapi(ffmpeg_path) if ffmpeg_probe.discoverable else HardwareProbe(
        backend="vaapi",
        detected=bool(intel_render),
        usable=False,
        status="failed",
        message=(
            "FFmpeg is not discoverable, so Intel VAAPI cannot be tested."
        ),
        details={
            "device_paths": [_device_probe(intel_render)] if intel_render else [],
            "hwaccels": hwaccels,
            "reason_unavailable": "ffmpeg missing",
        },
    )
    intel_usable = intel_vaapi_probe.usable
    intel_reason = None if intel_usable else (intel_vaapi_probe.details.get("reason_unavailable") or intel_vaapi_probe.message)
    intel_probe = HardwareProbe(
        backend="intel_igpu",
        detected=intel_render is not None or qsv_probe.detected or any("intel" in item.lower() for item in windows_adapters),
        usable=intel_usable,
        status="healthy" if intel_usable else "failed",
        message=(
            "Intel iGPU is available via VAAPI in this runtime."
            if intel_usable
            else "Intel iGPU passthrough is not fully usable in this runtime."
        ),
        details={
            "device_paths": [item for item in [_device_probe_from_path(intel_render), _device_probe_from_path(intel_card)] if item is not None],
            "ffmpeg_hwaccels": hwaccels,
            "ffmpeg_path_verified": intel_vaapi_probe.usable,
            "reason_unavailable": intel_reason,
            "recommended_usage": (
                "Use Intel VAAPI once the render node, vainfo validation, and FFmpeg smoke test all succeed."
                if intel_usable
                else "Expose /dev/dri to the worker runtime and validate Intel VAAPI before selecting Intel iGPU."
            ),
            "qsv": qsv_probe.details | {"usable": qsv_probe.usable, "message": qsv_probe.message, "status": qsv_probe.status},
            "vaapi": intel_vaapi_probe.details | {"usable": intel_vaapi_probe.usable, "message": intel_vaapi_probe.message},
            "windows_adapters": windows_adapters,
        },
    )

    nvidia_probe = probe_nvenc(ffmpeg_path) if ffmpeg_probe.discoverable else HardwareProbe(
        backend="nvidia_gpu",
        detected=False,
        usable=False,
        status="failed",
        message="FFmpeg is not discoverable, so NVIDIA support cannot be tested.",
        details={"device_paths": [], "hwaccels": hwaccels},
    )
    nvidia_probe = HardwareProbe(
        backend="nvidia_gpu",
        detected=nvidia_probe.detected,
        usable=nvidia_probe.usable,
        status=nvidia_probe.status,
        message=nvidia_probe.message,
        details=nvidia_probe.details
        | {
            "ffmpeg_path_verified": nvidia_probe.usable,
            "reason_unavailable": None if nvidia_probe.usable else nvidia_probe.message,
            "recommended_usage": (
                "Use NVENC when NVIDIA devices and runtime libraries are exposed to the container."
                if nvidia_probe.usable
                else "Expose /dev/nvidia* devices and the NVIDIA container runtime before selecting this backend."
            ),
        },
    )

    amd_vaapi_probe = probe_vaapi(ffmpeg_path, device_path=amd_render) if ffmpeg_probe.discoverable and amd_render else HardwareProbe(
        backend="vaapi",
        detected=bool(amd_render),
        usable=False,
        status="failed",
        message=(
            "AMD render device is not visible to the runtime."
            if amd_render is None
            else "AMD VAAPI could not be tested."
        ),
        details={"device_paths": [_device_probe(amd_render)] if amd_render else [], "hwaccels": hwaccels},
    )
    amd_amf_probe = probe_amf(ffmpeg_path) if ffmpeg_probe.discoverable else HardwareProbe(
        backend="amd_gpu",
        detected=False,
        usable=False,
        status="failed",
        message="FFmpeg is not discoverable, so AMD AMF cannot be tested.",
        details={"hwaccels": hwaccels},
    )
    amd_probe = HardwareProbe(
        backend="amd_gpu",
        detected=amd_render is not None or amd_amf_probe.detected,
        usable=amd_vaapi_probe.usable or amd_amf_probe.usable,
        status="healthy" if amd_vaapi_probe.usable or amd_amf_probe.usable else "failed",
        message=(
            "AMD GPU video acceleration is available to FFmpeg."
            if amd_vaapi_probe.usable or amd_amf_probe.usable
            else "AMD GPU passthrough is not fully usable by FFmpeg."
        ),
        details={
            "device_paths": [_device_probe(amd_render)] if amd_render else [],
            "ffmpeg_hwaccels": hwaccels,
            "ffmpeg_path_verified": amd_vaapi_probe.usable or amd_amf_probe.usable,
            "reason_unavailable": None if amd_vaapi_probe.usable or amd_amf_probe.usable else (amd_vaapi_probe.message or amd_amf_probe.message),
            "recommended_usage": (
                "Use AMD via VAAPI on Linux runtimes or AMF on supported Windows workers."
                if amd_vaapi_probe.usable or amd_amf_probe.usable
                else "Expose the AMD render device on Linux or verify AMF support on Windows before selecting this backend."
            ),
            "vaapi": amd_vaapi_probe.details | {"usable": amd_vaapi_probe.usable, "message": amd_vaapi_probe.message},
            "amf": amd_amf_probe.details | {"usable": amd_amf_probe.usable, "message": amd_amf_probe.message},
        },
    )

    return [cpu_probe, intel_probe, nvidia_probe, amd_probe]


def probe_binary(configured_path: Path | str) -> BinaryProbe:
    resolved = Path(configured_path)
    if resolved.is_absolute():
        exists = resolved.exists()
        executable = exists and os.access(resolved, os.X_OK)
        discoverable = executable
        resolved_path = resolved.as_posix() if exists else None
    else:
        resolved_command = shutil.which(str(configured_path))
        exists = resolved_command is not None
        executable = exists
        discoverable = exists
        resolved_path = resolved_command

    if discoverable:
        status = "healthy"
        message = "Binary is discoverable and executable."
    else:
        status = "failed"
        message = "Binary is not discoverable or executable."

    return BinaryProbe(
        configured_path=str(configured_path),
        resolved_path=resolved_path,
        exists=exists,
        executable=executable,
        discoverable=discoverable,
        status=status,
        message=message,
    )


def detect_ffmpeg_hwaccels(ffmpeg_path: Path | str) -> list[str]:
    probe = probe_binary(ffmpeg_path)
    if not probe.discoverable:
        return []

    try:
        completed = subprocess.run(
            [probe.resolved_path or str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-hwaccels"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    if completed.returncode != 0:
        return []

    hwaccels: list[str] = []
    for line in completed.stdout.splitlines():
        cleaned = line.strip().lower()
        if not cleaned or cleaned == "hardware acceleration methods:":
            continue
        hwaccels.append(cleaned)
    return hwaccels


def probe_intel_qsv(ffmpeg_path: Path | str) -> HardwareProbe:
    hwaccels = detect_ffmpeg_hwaccels(ffmpeg_path)
    render_devices = sorted(path.as_posix() for path in Path("/dev/dri").glob("renderD*"))
    is_windows = os.name == "nt"

    if not render_devices and not is_windows:
        return HardwareProbe(
            backend="intel_qsv",
            detected=False,
            usable=False,
            status="failed",
            message="No Intel render device is visible to the runtime.",
            details={"hwaccels": hwaccels, "render_devices": render_devices},
        )

    if "qsv" not in hwaccels:
        return HardwareProbe(
            backend="intel_qsv",
            detected=True,
            usable=False,
            status="failed",
            message="FFmpeg does not report QSV hardware acceleration support.",
            details={"hwaccels": hwaccels, "render_devices": render_devices},
        )
    return HardwareProbe(
        backend="intel_qsv",
        detected=True,
        usable=False,
        status="unknown",
        message="Intel QSV is visible in FFmpeg but remains unverified in this runtime.",
        details={
            "hwaccels": hwaccels,
            "render_devices": render_devices,
            "reason_unavailable": "QSV remains deliberately unverified until a reliable smoke test is validated in production.",
        },
    )


def probe_directory(path: Path | str, *, writable_required: bool) -> dict[str, object]:
    resolved = Path(path)
    exists = resolved.exists()
    is_directory = resolved.is_dir()
    readable = os.access(resolved, os.R_OK) if exists else False
    writable = os.access(resolved, os.W_OK) if exists else False

    if not exists:
        status = "failed"
        message = "Path does not exist."
    elif not is_directory:
        status = "failed"
        message = "Path exists but is not a directory."
    elif not readable:
        status = "failed"
        message = "Path exists but is not readable."
    elif writable_required and not writable:
        status = "failed"
        message = "Path exists but is not writable."
    else:
        status = "healthy"
        message = "Path is available."

    return {
        "path": resolved.as_posix(),
        "exists": exists,
        "is_directory": is_directory,
        "readable": readable,
        "writable": writable,
        "status": status,
        "message": message,
    }
