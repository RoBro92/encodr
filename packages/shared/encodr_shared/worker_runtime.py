from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess


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

    resolved_ffmpeg = probe_binary(ffmpeg_path).resolved_path or str(ffmpeg_path)
    init_hw_device = "qsv=qsv"
    if not is_windows:
        device = render_devices[0]
        init_hw_device = f"qsv=qsv:{device}"
    command = [
        resolved_ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-init_hw_device",
        init_hw_device,
        "-filter_hw_device",
        "qsv",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=16x16:rate=1",
        "-frames:v",
        "1",
        "-vf",
        "format=nv12,hwupload=extra_hw_frames=8",
        "-c:v",
        "h264_qsv",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return HardwareProbe(
            backend="intel_qsv",
            detected=True,
            usable=False,
            status="failed",
            message=f"QSV probe could not be executed: {error}",
            details={"hwaccels": hwaccels, "render_devices": render_devices},
        )

    if completed.returncode == 0:
        return HardwareProbe(
            backend="intel_qsv",
            detected=True,
            usable=True,
            status="healthy",
            message="Intel QSV is available and FFmpeg can initialise it.",
            details={"hwaccels": hwaccels, "render_devices": render_devices},
        )

    stderr = (completed.stderr or completed.stdout or "").strip()
    return HardwareProbe(
        backend="intel_qsv",
        detected=True,
        usable=False,
        status="failed",
        message="Intel QSV hardware is visible but FFmpeg could not initialise it.",
        details={
            "hwaccels": hwaccels,
            "render_devices": render_devices,
            "stderr": stderr[:1000] if stderr else None,
        },
    )


def probe_vaapi(ffmpeg_path: Path | str) -> HardwareProbe:
    hwaccels = detect_ffmpeg_hwaccels(ffmpeg_path)
    render_devices = sorted(path.as_posix() for path in Path("/dev/dri").glob("renderD*"))

    if not render_devices:
        return HardwareProbe(
            backend="vaapi",
            detected=False,
            usable=False,
            status="failed",
            message="No VAAPI render device is visible to the runtime.",
            details={"hwaccels": hwaccels, "render_devices": render_devices},
        )

    if "vaapi" not in hwaccels:
        return HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=False,
            status="failed",
            message="FFmpeg does not report VAAPI hardware acceleration support.",
            details={"hwaccels": hwaccels, "render_devices": render_devices},
        )

    resolved_ffmpeg = probe_binary(ffmpeg_path).resolved_path or str(ffmpeg_path)
    device = render_devices[0]
    command = [
        resolved_ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-init_hw_device",
        f"vaapi=vaapi:{device}",
        "-filter_hw_device",
        "vaapi",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=16x16:rate=1",
        "-frames:v",
        "1",
        "-vf",
        "format=nv12,hwupload",
        "-c:v",
        "h264_vaapi",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=False,
            status="failed",
            message=f"VAAPI probe could not be executed: {error}",
            details={"hwaccels": hwaccels, "render_devices": render_devices},
        )

    if completed.returncode == 0:
        return HardwareProbe(
            backend="vaapi",
            detected=True,
            usable=True,
            status="healthy",
            message="VAAPI is available and FFmpeg can initialise it.",
            details={"hwaccels": hwaccels, "render_devices": render_devices},
        )

    stderr = (completed.stderr or completed.stdout or "").strip()
    return HardwareProbe(
        backend="vaapi",
        detected=True,
        usable=False,
        status="failed",
        message="VAAPI hardware is visible but FFmpeg could not initialise it.",
        details={
            "hwaccels": hwaccels,
            "render_devices": render_devices,
            "stderr": stderr[:1000] if stderr else None,
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
