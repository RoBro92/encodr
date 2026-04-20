from __future__ import annotations

from pathlib import Path

import pytest

from encodr_shared.update import UpdateCheckSettings, UpdateChecker
from encodr_shared.versioning import find_project_root, is_version_newer, parse_version, read_version


def test_read_version_uses_root_version_file(repo_root: Path) -> None:
    assert read_version(repo_root) == "0.1.0"
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
        current_version="0.1.0",
        settings=UpdateCheckSettings(
            enabled=True,
            metadata_url="https://updates.example.invalid/encodr.json",
            channel="internal",
            timeout_seconds=2,
        ),
        fetcher=lambda _url, _timeout: {
            "latest_version": "0.1.0",
            "channel": "internal",
        },
    )

    result = checker.check_now()

    assert result.status == "ok"
    assert result.latest_version == "0.1.0"
    assert result.update_available is False


def test_update_checker_reports_available_update() -> None:
    checker = UpdateChecker(
        current_version="0.1.0",
        settings=UpdateCheckSettings(
            enabled=True,
            metadata_url="https://updates.example.invalid/encodr.json",
            channel="internal",
            timeout_seconds=2,
        ),
        fetcher=lambda _url, _timeout: {
            "latest_version": "0.1.1",
            "channel": "internal",
            "download_url": "https://downloads.example.invalid/encodr-0.1.1.tar.gz",
            "release_notes_url": "https://downloads.example.invalid/encodr-0.1.1-notes",
        },
    )

    result = checker.check_now()

    assert result.status == "ok"
    assert result.latest_version == "0.1.1"
    assert result.update_available is True
    assert result.download_url == "https://downloads.example.invalid/encodr-0.1.1.tar.gz"


def test_update_checker_reports_upstream_error() -> None:
    checker = UpdateChecker(
        current_version="0.1.0",
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
