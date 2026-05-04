from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import zipfile

import encodr_shared.diagnostics as diagnostics
from encodr_shared.diagnostics import (
    build_diagnostic_bundle,
    configure_component_logging,
    read_log_events,
    redact_mapping,
    redact_paths,
    redact_secrets,
)


def test_diagnostic_redaction_removes_secrets() -> None:
    assert redact_secrets("postgresql://encodr:super-secret@db/encodr") == (
        "postgresql://[REDACTED]:[REDACTED]@db/encodr"
    )
    assert redact_secrets("redis://:redis-password@redis:6379/0") == "redis://[REDACTED]:[REDACTED]@redis:6379/0"
    assert redact_secrets("Authorization: Bearer live-token-123") == "Authorization: Bearer [REDACTED]"
    assert redact_secrets("Bearer live-token-123") == "Bearer [REDACTED]"
    assert redact_secrets("authorization=Basic abc123") == "authorization=Basic [REDACTED]"
    assert redact_secrets("basic abc123") == "basic [REDACTED]"
    assert redact_secrets('"authorization":"Bearer live-token-123"') == '"authorization":"Bearer [REDACTED]"'
    assert redact_secrets('authorization="Basic abc123"') == 'authorization="Basic [REDACTED]"'
    assert (
        redact_secrets("https://updates.example/latest?api_key=live-token-123&channel=stable")
        == "https://updates.example/latest?api_key=[REDACTED]&channel=stable"
    )
    assert redact_mapping({"pairing_token": "abc123", "nested": {"password": "secret"}}) == {
        "pairing_token": "[REDACTED]",
        "nested": {"password": "[REDACTED]"},
    }
    assert redact_mapping({"redis": {"url": "redis://:redis-password@redis:6379/0"}}) == {
        "redis": {"url": "redis://[REDACTED]:[REDACTED]@redis:6379/0"}
    }


def test_diagnostic_bundle_includes_expected_sections_and_redacts_paths(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "api.jsonl").write_text(
        json.dumps(
            {
                "timestamp": datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc).isoformat(),
                "level": "error",
                "component": "api",
                "logger": "encodr.jobs",
                "message": "Failed processing /media/Movies/Private Film.mkv token=abc123",
                "fields": {"source_path": "/media/Movies/Private Film.mkv"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    events = read_log_events(log_dir, component="api", redact_paths=True)
    assert events[0].message == "Failed processing [PATH] token=[REDACTED]"
    assert events[0].fields["source_path"] == "[PATH]"

    bundle = build_diagnostic_bundle(
        log_dir=log_dir,
        summary={"generated_at": "2026-04-27T12:00:00Z"},
        health={"runtime": {"status": "healthy"}},
        workers={"items": []},
        jobs_recent={"items": [{"source_path": "/media/Movies/Private Film.mkv"}]},
        config_summary={"database": {"dsn": "postgresql://encodr:secret@db/encodr"}},
        since=datetime(2026, 4, 27, 11, 0, tzinfo=timezone.utc),
        redact_paths=True,
    )
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(bundle)

    with zipfile.ZipFile(bundle_path) as archive:
        assert {
            "summary.json",
            "health.json",
            "workers.json",
            "jobs_recent.json",
            "config_summary_redacted.json",
            "logs/api.jsonl",
            "logs/worker.jsonl",
            "logs/worker-agent.jsonl",
            "logs/system.jsonl",
        }.issubset(set(archive.namelist()))
        assert "/media/Movies" not in archive.read("jobs_recent.json").decode("utf-8")
        assert "secret" not in archive.read("config_summary_redacted.json").decode("utf-8")


def test_path_redaction_handles_quoted_posix_windows_and_unc_paths() -> None:
    message = (
        "Failed '/media/Movies/Private Film.mkv': Permission denied; "
        'probe "C:\\Media\\Private Film.mkv"; '
        "'\\\\server\\share\\Private Film.mkv'"
    )

    redacted = redact_paths(message)

    assert "/media/Movies" not in redacted
    assert "C:\\Media" not in redacted
    assert "\\\\server\\share" not in redacted
    assert "'[PATH]': Permission denied" in redacted
    assert '"[PATH]"' in redacted


def test_read_log_events_filters_top_level_and_legacy_event_names(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "api.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc).isoformat(),
                        "level": "info",
                        "component": "api",
                        "logger": "encodr.jobs",
                        "event": "job_created",
                        "message": "queued job",
                        "fields": {"job_id": "job-1"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": datetime(2026, 4, 27, 12, 1, tzinfo=timezone.utc).isoformat(),
                        "level": "error",
                        "component": "api",
                        "logger": "encodr.jobs",
                        "message": "job failed",
                        "fields": {"event": "job_failed", "job_id": "job-2"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    created_events = read_log_events(log_dir, component="api", event="job_created")
    failed_events = read_log_events(log_dir, component="api", event="job_failed")

    assert len(created_events) == 1
    assert created_events[0].event == "job_created"
    assert created_events[0].fields["job_id"] == "job-1"
    assert len(failed_events) == 1
    assert failed_events[0].event == "job_failed"
    assert failed_events[0].fields["job_id"] == "job-2"


def test_component_logging_falls_back_when_existing_log_file_cannot_be_opened(tmp_path, monkeypatch) -> None:
    requested_log_dir = tmp_path / "data" / "logs"
    requested_log_dir.mkdir(parents=True)
    fallback_temp_dir = tmp_path / "tmp"
    fallback_temp_dir.mkdir()
    original_handler = diagnostics.TimedRotatingFileHandler

    def handler_factory(filename, *args, **kwargs):
        if str(filename) == (requested_log_dir / "api.jsonl").as_posix():
            raise PermissionError("existing log directory is not writable")
        return original_handler(filename, *args, **kwargs)

    monkeypatch.setattr(diagnostics, "TimedRotatingFileHandler", handler_factory)
    monkeypatch.setattr(diagnostics.tempfile, "gettempdir", lambda: fallback_temp_dir.as_posix())

    log_path = configure_component_logging(component="api", log_dir=requested_log_dir)
    try:
        assert log_path == fallback_temp_dir / "encodr-logs" / "api.jsonl"
        assert log_path.exists()
    finally:
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if getattr(handler, "_encodr_log_path", None) == log_path.as_posix():
                root_logger.removeHandler(handler)
                handler.close()


def test_component_logging_uses_stdout_when_file_and_fallback_logging_fail(tmp_path, monkeypatch) -> None:
    requested_log_dir = tmp_path / "data" / "logs"
    fallback_temp_dir = tmp_path / "tmp"
    fallback_temp_dir.mkdir()

    def failing_handler_factory(filename, *args, **kwargs):  # type: ignore[no-untyped-def]
        del filename, args, kwargs
        raise PermissionError("diagnostic target is not writable")

    monkeypatch.setattr(diagnostics, "TimedRotatingFileHandler", failing_handler_factory)
    monkeypatch.setattr(diagnostics.tempfile, "gettempdir", lambda: fallback_temp_dir.as_posix())

    log_path = configure_component_logging(component="api", log_dir=requested_log_dir)
    try:
        assert log_path == Path("stdout")
    finally:
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if getattr(handler, "_encodr_log_path", None) == "stdout":
                root_logger.removeHandler(handler)
                handler.close()
