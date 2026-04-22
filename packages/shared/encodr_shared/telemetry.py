from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
from typing import Any

from encodr_shared.worker_runtime import discover_runtime_devices

try:
    import resource
except ImportError:  # pragma: no cover - Windows does not expose resource.
    resource = None  # type: ignore[assignment]

_SYSTEM_CPU_SAMPLE: tuple[float, float, float] | None = None
_PROCESS_CPU_SAMPLE: tuple[float, float] | None = None


def collect_runtime_telemetry(*, current_backend: str | None = None) -> dict[str, Any]:
    memory = _sample_memory()
    telemetry: dict[str, Any] = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "backend_in_use": current_backend,
        "cpu_usage_percent": _sample_system_cpu_percent(),
        "process_cpu_usage_percent": _sample_process_cpu_percent(),
        "memory_total_bytes": memory.get("total_bytes"),
        "memory_available_bytes": memory.get("available_bytes"),
        "memory_used_bytes": memory.get("used_bytes"),
        "memory_usage_percent": memory.get("usage_percent"),
        "process_memory_bytes": _sample_process_memory_bytes(),
        "cpu_temperature_c": _sample_cpu_temperature_c(),
        "gpu": _sample_gpu_telemetry(current_backend=current_backend),
    }
    return telemetry


def _sample_system_cpu_percent() -> float | None:
    if os.name != "posix":
        return None

    first = _read_proc_stat()
    if first is None:
        return None
    previous = _populated_system_sample(first)
    if previous is None:
        time.sleep(0.05)
        current = _read_proc_stat()
        if current is None:
            return None
        _store_system_cpu_sample(current)
        return _calculate_cpu_percent(previous=first, current=current)

    _store_system_cpu_sample(first)
    return _calculate_cpu_percent(previous=(previous[1], previous[2]), current=first)


def _read_proc_stat() -> tuple[float, float] | None:
    stat_path = Path("/proc/stat")
    if not stat_path.exists():
        return None
    try:
        first_line = stat_path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    parts = first_line.split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None
    try:
        values = [float(part) for part in parts[1:]]
    except ValueError:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0.0)
    total = sum(values)
    return idle, total


def _populated_system_sample(current: tuple[float, float]) -> tuple[float, float, float] | None:
    global _SYSTEM_CPU_SAMPLE
    sample = _SYSTEM_CPU_SAMPLE
    if sample is None:
        _SYSTEM_CPU_SAMPLE = (time.monotonic(), current[0], current[1])
        return None
    return sample


def _store_system_cpu_sample(current: tuple[float, float]) -> None:
    global _SYSTEM_CPU_SAMPLE
    _SYSTEM_CPU_SAMPLE = (time.monotonic(), current[0], current[1])


def _calculate_cpu_percent(
    *,
    previous: tuple[float, float],
    current: tuple[float, float],
) -> float | None:
    previous_idle, previous_total = previous
    current_idle, current_total = current
    total_delta = current_total - previous_total
    idle_delta = current_idle - previous_idle
    if total_delta <= 0:
        return None
    usage = max(0.0, min(((total_delta - idle_delta) / total_delta) * 100.0, 100.0))
    return round(usage, 1)


def _sample_process_cpu_percent() -> float | None:
    current_wall = time.monotonic()
    current_cpu = time.process_time()
    global _PROCESS_CPU_SAMPLE
    previous = _PROCESS_CPU_SAMPLE
    _PROCESS_CPU_SAMPLE = (current_wall, current_cpu)

    if previous is None:
        time.sleep(0.05)
        next_wall = time.monotonic()
        next_cpu = time.process_time()
        _PROCESS_CPU_SAMPLE = (next_wall, next_cpu)
        elapsed = next_wall - current_wall
        if elapsed <= 0:
            return None
        usage = (next_cpu - current_cpu) / elapsed * 100.0
        return round(max(0.0, usage), 1)

    previous_wall, previous_cpu = previous
    elapsed = current_wall - previous_wall
    if elapsed <= 0:
        return None
    usage = (current_cpu - previous_cpu) / elapsed * 100.0
    return round(max(0.0, usage), 1)


def _sample_memory() -> dict[str, float | int | None]:
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return {
            "total_bytes": None,
            "available_bytes": None,
            "used_bytes": None,
            "usage_percent": None,
        }

    parsed: dict[str, int] = {}
    try:
        for line in meminfo_path.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            parts = value.strip().split()
            if not parts:
                continue
            parsed[key] = int(parts[0]) * 1024
    except (OSError, ValueError):
        return {
            "total_bytes": None,
            "available_bytes": None,
            "used_bytes": None,
            "usage_percent": None,
        }

    total = parsed.get("MemTotal")
    available = parsed.get("MemAvailable")
    if total is None or available is None:
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": None,
            "usage_percent": None,
        }

    used = max(total - available, 0)
    usage_percent = round((used / total) * 100.0, 1) if total > 0 else None
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "usage_percent": usage_percent,
    }


def _sample_process_memory_bytes() -> int | None:
    status_path = Path("/proc/self/status")
    if status_path.exists():
        try:
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if not line.startswith("VmRSS:"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * 1024
        except (OSError, ValueError):
            return None

    if resource is None:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError:
        return None
    if usage.ru_maxrss <= 0:
        return None
    # ru_maxrss is kilobytes on Linux and bytes on macOS/BSD.
    if sys.platform == "darwin":
        return int(usage.ru_maxrss)
    return int(usage.ru_maxrss * 1024)


def _sample_gpu_telemetry(*, current_backend: str | None) -> dict[str, Any] | None:
    nvidia = _sample_nvidia_telemetry()
    if nvidia is not None:
        return nvidia

    if current_backend in {"intel_igpu", "amd_gpu"}:
        temperature = _sample_linux_drm_temperature(current_backend)
        if temperature is not None:
            return {
                "vendor": "Intel" if current_backend == "intel_igpu" else "AMD",
                "status": "partial",
                "usage_percent": None,
                "memory_used_bytes": None,
                "memory_total_bytes": None,
                "temperature_c": temperature,
                "message": "Only temperature telemetry is currently available for this backend in this runtime.",
            }
        return {
            "vendor": "Intel" if current_backend == "intel_igpu" else "AMD",
            "status": "unavailable",
            "usage_percent": None,
            "memory_used_bytes": None,
            "memory_total_bytes": None,
            "temperature_c": None,
            "message": "No readable GPU telemetry source is available for this backend in this runtime.",
        }

    return None


def _sample_nvidia_telemetry() -> dict[str, Any] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,name",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    first = [part.strip() for part in lines[0].split(",")]
    if len(first) < 5:
        return None
    usage_percent = _parse_optional_float(first[0])
    temperature_c = _parse_optional_float(first[1])
    memory_used_mib = _parse_optional_float(first[2])
    memory_total_mib = _parse_optional_float(first[3])
    return {
        "vendor": "NVIDIA",
        "device_name": first[4] or None,
        "status": "healthy",
        "usage_percent": usage_percent,
        "memory_used_bytes": _mib_to_bytes(memory_used_mib),
        "memory_total_bytes": _mib_to_bytes(memory_total_mib),
        "temperature_c": temperature_c,
        "message": "Telemetry is being read from nvidia-smi.",
    }


def _sample_linux_drm_temperature(backend: str) -> float | None:
    if os.name != "posix":
        return None
    vendor = "Intel" if backend == "intel_igpu" else "AMD"
    for device in discover_runtime_devices():
        if device.get("vendor_name") != vendor:
            continue
        device_path = str(device.get("path") or "")
        name = Path(device_path).name
        if not name:
            continue
        base = Path("/sys/class/drm") / name / "device" / "hwmon"
        if not base.exists():
            continue
        for temp_file in sorted(base.glob("hwmon*/temp*_input")):
            try:
                raw = temp_file.read_text(encoding="utf-8").strip()
                return round(int(raw) / 1000.0, 1)
            except (OSError, ValueError):
                continue
    return None


def _sample_cpu_temperature_c() -> float | None:
    thermal_root = Path("/sys/class/thermal")
    if not thermal_root.exists():
        return None
    for temp_file in sorted(thermal_root.glob("thermal_zone*/temp")):
        try:
            raw = temp_file.read_text(encoding="utf-8").strip()
            value = int(raw)
        except (OSError, ValueError):
            continue
        if value <= 0:
            continue
        return round(value / 1000.0, 1) if value > 1000 else round(float(value), 1)
    return None


def _parse_optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"n/a", "[not supported]"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _mib_to_bytes(value: float | None) -> int | None:
    if value is None:
        return None
    return int(value * 1024 * 1024)
