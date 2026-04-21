from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen

from encodr_shared.versioning import is_version_newer

DEFAULT_RELEASE_METADATA_URL = "https://api.github.com/repos/RoBro92/encodr/releases/latest"


UpdateFetcher = Callable[[str, int], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class UpdateCheckSettings:
    enabled: bool
    metadata_url: str | None
    channel: str
    timeout_seconds: int = 5


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str | None
    update_available: bool
    channel: str
    status: str
    release_name: str | None = None
    release_summary: str | None = None
    checked_at: datetime | None = None
    error: str | None = None
    download_url: str | None = None
    release_notes_url: str | None = None


def default_update_fetcher(metadata_url: str, timeout_seconds: int) -> dict[str, Any]:
    with urlopen(metadata_url, timeout=timeout_seconds) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Update metadata must be a JSON object.")
    return payload


class UpdateChecker:
    def __init__(
        self,
        *,
        current_version: str,
        settings: UpdateCheckSettings,
        fetcher: UpdateFetcher | None = None,
    ) -> None:
        self.current_version = current_version
        self.settings = settings
        self.fetcher = fetcher or default_update_fetcher
        self._last_result = self._default_result()

    def _default_result(self) -> UpdateCheckResult:
        status = "disabled" if not self.settings.enabled else "not_checked"
        return UpdateCheckResult(
            current_version=self.current_version,
            latest_version=None,
            update_available=False,
            channel=self.settings.channel,
            status=status,
        )

    def current_status(self, *, auto_check: bool = False) -> UpdateCheckResult:
        if auto_check and self.settings.enabled and self._last_result.status == "not_checked":
            return self.check_now()
        return self._last_result

    def check_now(self) -> UpdateCheckResult:
        if not self.settings.enabled:
            self._last_result = replace(self._default_result(), status="disabled")
            return self._last_result

        if not self.settings.metadata_url:
            self._last_result = UpdateCheckResult(
                current_version=self.current_version,
                latest_version=None,
                update_available=False,
                channel=self.settings.channel,
                status="misconfigured",
                checked_at=datetime.now(timezone.utc),
                error="Update checks are enabled but no metadata URL is configured.",
            )
            return self._last_result

        checked_at = datetime.now(timezone.utc)
        try:
            payload = self.fetcher(self.settings.metadata_url, self.settings.timeout_seconds)
            latest_version = _extract_latest_version(payload)
            if latest_version is None:
                raise ValueError("Update metadata did not include latest_version.")

            channel = str(payload.get("channel") or self.settings.channel)
            download_url = _optional_text(payload.get("download_url")) or _optional_text(payload.get("tarball_url"))
            release_notes_url = _optional_text(payload.get("release_notes_url")) or _optional_text(payload.get("html_url"))
            release_name = _optional_text(payload.get("release_name")) or _optional_text(payload.get("name"))
            release_summary = _extract_release_summary(payload)

            self._last_result = UpdateCheckResult(
                current_version=self.current_version,
                latest_version=latest_version,
                update_available=is_version_newer(self.current_version, latest_version),
                channel=channel,
                status="ok",
                release_name=release_name,
                release_summary=release_summary,
                checked_at=checked_at,
                download_url=download_url,
                release_notes_url=release_notes_url,
            )
            return self._last_result
        except (URLError, ValueError, OSError, json.JSONDecodeError) as error:
            self._last_result = UpdateCheckResult(
                current_version=self.current_version,
                latest_version=None,
                update_available=False,
                channel=self.settings.channel,
                status="error",
                checked_at=checked_at,
                error=str(error),
            )
            return self._last_result


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_latest_version(payload: dict[str, Any]) -> str | None:
    for key in ("latest_version", "version"):
        value = _optional_text(payload.get(key))
        if value:
            return value

    tag_name = _optional_text(payload.get("tag_name"))
    if not tag_name:
        return None
    return tag_name[1:] if tag_name.startswith(("v", "V")) else tag_name


def _extract_release_summary(payload: dict[str, Any]) -> str | None:
    body = _optional_text(payload.get("release_summary")) or _optional_text(payload.get("body"))
    if not body:
        return None

    lines = [line.strip() for line in body.splitlines()]
    meaningful_lines = [line for line in lines if line]
    if not meaningful_lines:
        return None

    summary_lines = meaningful_lines[:4]
    summary = "\n".join(summary_lines)
    if len(meaningful_lines) > 4 or len(summary) > 420:
        summary = summary[:420].rstrip()
        if not summary.endswith("..."):
            summary = f"{summary}..."
    return summary
