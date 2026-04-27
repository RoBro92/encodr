from __future__ import annotations

from datetime import datetime, timezone
import json
import zipfile

from encodr_shared.diagnostics import build_diagnostic_bundle, read_log_events, redact_mapping, redact_secrets


def test_diagnostic_redaction_removes_secrets() -> None:
    assert redact_secrets("postgresql://encodr:super-secret@db/encodr") == (
        "postgresql://[REDACTED]:[REDACTED]@db/encodr"
    )
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
