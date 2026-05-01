from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import zipfile

import encodr_shared.diagnostics as diagnostics
from encodr_shared.diagnostics import (
    build_diagnostic_bundle,
    configure_component_logging,
    read_log_events,
    redact_mapping,
    redact_secrets,
)


def test_diagnostic_redaction_removes_secrets() -> None:
    assert redact_secrets("postgresql://encodr:super-secret@db/encodr") == (
        "postgresql://[REDACTED]:[REDACTED]@db/encodr"
    )
    assert redact_secrets("Authorization: Bearer live-token-123") == "Authorization: Bearer [REDACTED]"
    assert redact_secrets("authorization=Basic abc123") == "authorization=Basic [REDACTED]"
    assert redact_secrets('"authorization":"Bearer live-token-123"') == '"authorization":"Bearer [REDACTED]"'
    assert redact_secrets('authorization="Basic abc123"') == 'authorization="Basic [REDACTED]"'
    assert redact_mapping({"pairing_token": "abc123", "nested": {"password": "secret"}}) == {
        "pairing_token": "[REDACTED]",
        "nested": {"password": "[REDACTED]"},
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
