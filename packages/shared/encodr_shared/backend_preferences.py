from __future__ import annotations

from collections.abc import Iterable
from typing import Any

DEFAULT_BACKEND_PREFERENCE = "cpu_only"
DEFAULT_NORMALISED_BACKEND = "cpu"
CPU_HARDWARE_HINT = "cpu_only"

SUPPORTED_BACKEND_PREFERENCES = frozenset(
    {
        "cpu_only",
        "prefer_intel_igpu",
        "intel_auto",
        "intel_qsv",
        "intel_vaapi",
        "prefer_nvidia_gpu",
        "prefer_amd_gpu",
    }
)

BACKEND_PREFERENCE_LABELS = {
    "cpu_only": "CPU only",
    "cpu": "CPU only",
    "prefer_intel_igpu": "Intel auto",
    "intel_igpu": "Intel auto",
    "intel_auto": "Intel auto",
    "intel_qsv": "Intel QSV",
    "intel_vaapi": "Intel VAAPI",
    "prefer_nvidia_gpu": "NVIDIA GPU",
    "nvidia_gpu": "NVIDIA GPU",
    "prefer_amd_gpu": "AMD GPU",
    "amd_gpu": "AMD GPU",
}

BACKEND_PREFERENCE_KEYS = {
    "cpu": "cpu_only",
    "intel_igpu": "prefer_intel_igpu",
    "nvidia_gpu": "prefer_nvidia_gpu",
    "amd_gpu": "prefer_amd_gpu",
}

BACKEND_ADDITIONAL_PREFERENCE_KEYS = {
    "cpu": ["cpu"],
    "intel_igpu": ["intel_auto", "intel_qsv", "intel_vaapi", "qsv", "vaapi", "auto"],
    "nvidia_gpu": ["nvidia_gpu"],
    "amd_gpu": ["amd_gpu"],
}

BACKEND_PREFERENCE_ALIASES = {
    "cpu_only": "cpu",
    "cpu": "cpu",
    "prefer_intel_igpu": "intel_auto",
    "intel_igpu": "intel_auto",
    "intel_auto": "intel_auto",
    "auto": "intel_auto",
    "qsv": "intel_qsv",
    "intel_qsv": "intel_qsv",
    "vaapi": "intel_vaapi",
    "intel_vaapi": "intel_vaapi",
    "prefer_nvidia_gpu": "nvidia_gpu",
    "nvidia_gpu": "nvidia_gpu",
    "prefer_amd_gpu": "amd_gpu",
    "amd_gpu": "amd_gpu",
}

INTEL_BACKEND_PREFERENCES = frozenset({"intel_auto", "intel_qsv", "intel_vaapi"})
ACCELERATED_HARDWARE_HINTS = frozenset(
    {"nvidia_gpu", "amd_gpu", "intel_igpu", "intel_qsv", "intel_vaapi"}
)


def backend_preference_key(backend: str) -> str:
    return BACKEND_PREFERENCE_KEYS.get(backend, backend)


def backend_preference_keys(backend: str) -> list[str]:
    primary = backend_preference_key(backend)
    aliases = BACKEND_ADDITIONAL_PREFERENCE_KEYS.get(backend, [])
    return list(dict.fromkeys([primary, *aliases]))


def normalise_backend_preference_key(value: str | None) -> str:
    cleaned = str(value or DEFAULT_BACKEND_PREFERENCE).strip()
    return BACKEND_PREFERENCE_ALIASES.get(cleaned, DEFAULT_NORMALISED_BACKEND)


def coerce_backend_preference(value: object, *, default: str = DEFAULT_BACKEND_PREFERENCE) -> str:
    cleaned = str(value or "").strip()
    if cleaned in SUPPORTED_BACKEND_PREFERENCES:
        return cleaned
    canonical = backend_preference_key(normalise_backend_preference_key(cleaned))
    return canonical if canonical in SUPPORTED_BACKEND_PREFERENCES else default


def is_supported_backend_preference(value: object) -> bool:
    return str(value or "").strip() in SUPPORTED_BACKEND_PREFERENCES


def backend_preference_label(value: str | None) -> str:
    cleaned = str(value or DEFAULT_BACKEND_PREFERENCE).strip()
    if cleaned in BACKEND_PREFERENCE_LABELS:
        return BACKEND_PREFERENCE_LABELS[cleaned]
    normalised = normalise_backend_preference_key(cleaned)
    return BACKEND_PREFERENCE_LABELS.get(normalised, cleaned.replace("_", " ").title())


def probe_backend_for_preference(value: str | None) -> str:
    normalised = normalise_backend_preference_key(value)
    return "intel_igpu" if normalised in INTEL_BACKEND_PREFERENCES else normalised


def hardware_hints_from_backend_probes(
    probes: Iterable[object],
    *,
    fallback_hint: str = CPU_HARDWARE_HINT,
) -> list[str]:
    hints: list[str] = []
    for probe in probes:
        backend = _probe_field(probe, "backend")
        if backend == "cpu" or not _probe_usable(probe):
            continue
        hints.append(backend)
        details = _probe_details(probe)
        usable_backends = details.get("usable_backends")
        if isinstance(usable_backends, list):
            hints.extend(str(item) for item in usable_backends if item)
    if not hints:
        hints.append(fallback_hint)
    return list(dict.fromkeys(hints))


def _probe_field(probe: object, field: str) -> str:
    if isinstance(probe, dict):
        return str(probe.get(field) or "")
    return str(getattr(probe, field, "") or "")


def _probe_usable(probe: object) -> bool:
    if isinstance(probe, dict):
        return bool(probe.get("usable_by_ffmpeg", probe.get("usable", False)))
    return bool(getattr(probe, "usable", False))


def _probe_details(probe: object) -> dict[str, Any]:
    details = probe.get("details", {}) if isinstance(probe, dict) else getattr(probe, "details", {})
    return details if isinstance(details, dict) else {}
