from __future__ import annotations

import json
from pathlib import Path

import pytest

from encodr_shared.runtime_compose import (
    RuntimeComposeProfile,
    build_runtime_compose_profile,
    render_runtime_compose,
    write_runtime_compose_files,
)


pytestmark = [pytest.mark.unit]


def test_build_runtime_compose_profile_warns_when_nvidia_devices_exist_without_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "encodr_shared.runtime_compose.discover_runtime_devices",
        lambda: [
            {"path": "/dev/dri/renderD128", "exists": True},
            {"path": "/dev/nvidia0", "exists": True},
        ],
    )
    monkeypatch.setattr("encodr_shared.runtime_compose.detect_nvidia_runtime", lambda: False)

    profile = build_runtime_compose_profile()

    assert profile.dri_devices == ("/dev/dri/renderD128",)
    assert profile.nvidia_devices_present is True
    assert profile.nvidia_runtime_available is False
    assert profile.warnings == (
        "NVIDIA device nodes are present, but the Docker runtime does not report NVIDIA GPU support.",
    )


def test_render_runtime_compose_includes_dri_and_nvidia_configuration() -> None:
    rendered = render_runtime_compose(
        RuntimeComposeProfile(
            dri_devices=("/dev/dri/card0", "/dev/dri/renderD128"),
            nvidia_devices_present=True,
            nvidia_runtime_available=True,
            warnings=(),
        )
    )

    assert "services:" in rendered
    assert "/dev/dri/card0:/dev/dri/card0" in rendered
    assert "/dev/dri/renderD128:/dev/dri/renderD128" in rendered
    assert "/sys/class/drm:/sys/class/drm:ro" in rendered
    assert "gpus: all" in rendered
    assert "NVIDIA_DRIVER_CAPABILITIES: compute,utility,video" in rendered


def test_write_runtime_compose_files_writes_yaml_and_profile_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "encodr_shared.runtime_compose.build_runtime_compose_profile",
        lambda: RuntimeComposeProfile(
            dri_devices=("/dev/dri/renderD128",),
            nvidia_devices_present=False,
            nvidia_runtime_available=False,
            warnings=("Intel render device available.",),
        ),
    )

    profile = write_runtime_compose_files(tmp_path)

    compose_path = tmp_path / ".runtime" / "compose.runtime.yml"
    profile_path = tmp_path / ".runtime" / "compose.runtime.json"
    assert profile.dri_devices == ("/dev/dri/renderD128",)
    assert compose_path.exists()
    assert profile_path.exists()
    assert "/dev/dri/renderD128:/dev/dri/renderD128" in compose_path.read_text(encoding="utf-8")
    profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile_payload["warnings"] == ["Intel render device available."]
