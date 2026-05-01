from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from encodr_shared.runtime_compose import (
    RuntimeComposeProfile,
    build_runtime_compose_profile,
    render_runtime_compose,
    write_runtime_compose_files,
)


pytestmark = [pytest.mark.unit]


def _service_block(rendered: str, service_name: str) -> str:
    lines = rendered.splitlines()
    start = lines.index(f"  {service_name}:")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("  ") and not lines[index].startswith("    ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


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
    monkeypatch.setattr(
        "encodr_shared.runtime_compose.Path.stat",
        lambda self: SimpleNamespace(st_gid=993),
    )

    profile = build_runtime_compose_profile()

    assert profile.dri_devices == ("/dev/dri/renderD128",)
    assert profile.dri_device_group_ids == ("993",)
    assert profile.nvidia_devices_present is True
    assert profile.nvidia_runtime_available is False
    assert profile.warnings == (
        "NVIDIA device nodes are present, but the Docker runtime does not report NVIDIA GPU support.",
    )


def test_build_runtime_compose_profile_detects_dri_device_group_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "encodr_shared.runtime_compose.discover_runtime_devices",
        lambda: [
            {"path": "/dev/dri/renderD128", "exists": True},
            {"path": "/dev/dri/card1", "exists": True},
        ],
    )
    monkeypatch.setattr("encodr_shared.runtime_compose.detect_nvidia_runtime", lambda: False)

    real_stat = Path.stat

    def fake_stat(self: Path) -> SimpleNamespace:
        groups = {"/dev/dri/card1": 44, "/dev/dri/renderD128": 993}
        if self.as_posix() in groups:
            return SimpleNamespace(st_gid=groups[self.as_posix()])
        return real_stat(self)

    monkeypatch.setattr("encodr_shared.runtime_compose.Path.stat", fake_stat)

    profile = build_runtime_compose_profile()

    assert profile.dri_devices == ("/dev/dri/card1", "/dev/dri/renderD128")
    assert profile.dri_device_group_ids == ("44", "993")


def test_build_runtime_compose_profile_collapses_duplicate_dri_device_group_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "encodr_shared.runtime_compose.discover_runtime_devices",
        lambda: [
            {"path": "/dev/dri/renderD128", "exists": True},
            {"path": "/dev/dri/card1", "exists": True},
        ],
    )
    monkeypatch.setattr("encodr_shared.runtime_compose.detect_nvidia_runtime", lambda: False)
    real_stat = Path.stat

    def fake_stat(self: Path) -> SimpleNamespace:
        if self.as_posix().startswith("/dev/dri/"):
            return SimpleNamespace(st_gid=993)
        return real_stat(self)

    monkeypatch.setattr("encodr_shared.runtime_compose.Path.stat", fake_stat)

    profile = build_runtime_compose_profile()

    assert profile.dri_device_group_ids == ("993",)


def test_build_runtime_compose_profile_skips_unstatable_dri_device_group_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "encodr_shared.runtime_compose.discover_runtime_devices",
        lambda: [
            {"path": "/dev/dri/renderD128", "exists": True},
            {"path": "/dev/dri/card1", "exists": True},
        ],
    )
    monkeypatch.setattr("encodr_shared.runtime_compose.detect_nvidia_runtime", lambda: False)

    real_stat = Path.stat

    def fake_stat(self: Path) -> SimpleNamespace:
        if self.as_posix() == "/dev/dri/card1":
            return SimpleNamespace(st_gid=44)
        if not self.as_posix().startswith("/dev/dri/"):
            return real_stat(self)
        raise PermissionError("stat denied")

    monkeypatch.setattr("encodr_shared.runtime_compose.Path.stat", fake_stat)

    profile = build_runtime_compose_profile()

    assert profile.dri_device_group_ids == ("44",)
    assert profile.warnings == (
        "Unable to inspect /dev/dri/renderD128 for device group access; skipping group_add entry.",
    )


def test_render_runtime_compose_omits_group_add_without_dri_devices() -> None:
    rendered = render_runtime_compose(
        RuntimeComposeProfile(
            dri_devices=(),
            dri_device_group_ids=(),
            nvidia_devices_present=False,
            nvidia_runtime_available=False,
            warnings=(),
        )
    )

    assert "services: {}" in rendered
    assert "group_add:" not in rendered


def test_render_runtime_compose_omits_group_add_when_profile_has_no_dri_devices() -> None:
    rendered = render_runtime_compose(
        RuntimeComposeProfile(
            dri_devices=(),
            dri_device_group_ids=("993",),
            nvidia_devices_present=True,
            nvidia_runtime_available=True,
            warnings=(),
        )
    )

    assert "gpus: all" in rendered
    assert "devices:" not in rendered
    assert "group_add:" not in rendered


def test_render_runtime_compose_includes_dri_and_nvidia_configuration() -> None:
    rendered = render_runtime_compose(
        RuntimeComposeProfile(
            dri_devices=("/dev/dri/card0", "/dev/dri/renderD128"),
            dri_device_group_ids=("44", "993"),
            nvidia_devices_present=True,
            nvidia_runtime_available=True,
            warnings=(),
        )
    )

    assert "services:" in rendered
    assert "/dev/dri/card0:/dev/dri/card0" in rendered
    assert "/dev/dri/renderD128:/dev/dri/renderD128" in rendered
    assert "/sys/class/drm:/sys/class/drm:ro" in rendered
    assert "/sys/class/hwmon:/sys/class/hwmon:ro" in rendered
    assert '      - "44"' in rendered
    assert '      - "993"' in rendered
    assert "gpus: all" in rendered
    assert "NVIDIA_DRIVER_CAPABILITIES: compute,utility,video" in rendered

    for service_name in ("api", "worker", "worker-agent"):
        block = _service_block(rendered, service_name)
        assert "/dev/dri/card0:/dev/dri/card0" in block
        assert "/dev/dri/renderD128:/dev/dri/renderD128" in block
        assert "group_add:" in block
        assert '      - "44"' in block
        assert '      - "993"' in block


def test_render_runtime_compose_does_not_use_privileged_or_world_writable_device_workarounds() -> None:
    rendered = render_runtime_compose(
        RuntimeComposeProfile(
            dri_devices=("/dev/dri/renderD128",),
            dri_device_group_ids=("993",),
            nvidia_devices_present=False,
            nvidia_runtime_available=False,
            warnings=(),
        )
    )

    assert "privileged:" not in rendered
    assert "chmod" not in rendered
    assert "777" not in rendered


def test_write_runtime_compose_files_writes_yaml_and_profile_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "encodr_shared.runtime_compose.build_runtime_compose_profile",
        lambda: RuntimeComposeProfile(
            dri_devices=("/dev/dri/renderD128",),
            dri_device_group_ids=("993",),
            nvidia_devices_present=False,
            nvidia_runtime_available=False,
            warnings=("Intel render device available.",),
        ),
    )

    profile = write_runtime_compose_files(tmp_path)

    compose_path = tmp_path / ".runtime" / "compose.runtime.yml"
    profile_path = tmp_path / ".runtime" / "compose.runtime.json"
    assert profile.dri_devices == ("/dev/dri/renderD128",)
    assert profile.dri_device_group_ids == ("993",)
    assert compose_path.exists()
    assert profile_path.exists()
    assert "/dev/dri/renderD128:/dev/dri/renderD128" in compose_path.read_text(encoding="utf-8")
    assert '      - "993"' in compose_path.read_text(encoding="utf-8")
    profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile_payload["dri_device_group_ids"] == ["993"]
    assert profile_payload["warnings"] == ["Intel render device available."]
