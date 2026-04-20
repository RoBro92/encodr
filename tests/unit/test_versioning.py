from __future__ import annotations

from pathlib import Path

import pytest

from encodr_shared.update import UpdateCheckSettings, UpdateChecker
from encodr_shared.versioning import find_project_root, is_version_newer, parse_version, read_version

CURRENT_VERSION = read_version(Path(__file__))


def next_patch_version(version: str) -> str:
    parts = list(parse_version(version))
    parts[-1] += 1
    return ".".join(str(part) for part in parts)


def test_read_version_uses_root_version_file(repo_root: Path) -> None:
    assert read_version(repo_root) == CURRENT_VERSION
    assert find_project_root(repo_root / "apps" / "api") == repo_root


def test_parse_version_accepts_dotted_numeric_values() -> None:
    assert parse_version("0.1.0") == (0, 1, 0)


def test_parse_version_rejects_invalid_versions() -> None:
    with pytest.raises(ValueError):
        parse_version("release-candidate")


def test_is_version_newer_handles_numeric_and_non_numeric_versions() -> None:
    assert is_version_newer("0.1.0", "0.1.1") is True
    assert is_version_newer("0.1.1", "0.1.0") is False
    assert is_version_newer("0.1.0", "0.1.0-beta") is False
    assert is_version_newer("0.1.0", "0.1.0+build.2") is True


def test_update_checker_reports_no_update() -> None:
    checker = UpdateChecker(
        current_version=CURRENT_VERSION,
        settings=UpdateCheckSettings(
            enabled=True,
            metadata_url="https://updates.example.invalid/encodr.json",
            channel="internal",
            timeout_seconds=2,
        ),
        fetcher=lambda _url, _timeout: {
            "latest_version": CURRENT_VERSION,
            "channel": "internal",
        },
    )

    result = checker.check_now()

    assert result.status == "ok"
    assert result.latest_version == CURRENT_VERSION
    assert result.update_available is False


def test_update_checker_reports_available_update() -> None:
    latest_version = next_patch_version(CURRENT_VERSION)
    checker = UpdateChecker(
        current_version=CURRENT_VERSION,
        settings=UpdateCheckSettings(
            enabled=True,
            metadata_url="https://updates.example.invalid/encodr.json",
            channel="internal",
            timeout_seconds=2,
        ),
        fetcher=lambda _url, _timeout: {
            "latest_version": latest_version,
            "channel": "internal",
            "download_url": f"https://downloads.example.invalid/encodr-{latest_version}.tar.gz",
            "release_notes_url": f"https://downloads.example.invalid/encodr-{latest_version}-notes",
        },
    )

    result = checker.check_now()

    assert result.status == "ok"
    assert result.latest_version == latest_version
    assert result.update_available is True
    assert result.download_url == f"https://downloads.example.invalid/encodr-{latest_version}.tar.gz"


def test_update_checker_reports_upstream_error() -> None:
    checker = UpdateChecker(
        current_version=CURRENT_VERSION,
        settings=UpdateCheckSettings(
            enabled=True,
            metadata_url="https://updates.example.invalid/encodr.json",
            channel="internal",
            timeout_seconds=2,
        ),
        fetcher=lambda _url, _timeout: (_ for _ in ()).throw(ValueError("metadata unavailable")),
    )

    result = checker.check_now()

    assert result.status == "error"
    assert result.update_available is False
    assert result.error == "metadata unavailable"
