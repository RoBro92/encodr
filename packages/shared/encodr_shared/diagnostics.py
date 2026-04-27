from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import io
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import re
import tempfile
from typing import Any
import zipfile

SECRET_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|dsn|pairing)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|pairing)(['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+"
)
DSN_CREDENTIAL_PATTERN = re.compile(r"([a-z][a-z0-9+.-]*://)([^:/@\s]+):([^@\s]+)@", re.IGNORECASE)
PATH_PATTERN = re.compile(
    r"(?<![\w.-])/(?:[^\n\r\"'{}]+?)(?=\s+(?:password|passwd|secret|token|api[_-]?key|authorization|pairing)\b|[,}\]\n\r]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DiagnosticLogEvent:
    timestamp: str
    level: str
    component: str
    logger: str
    message: str
    fields: dict[str, Any]


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, component: str) -> None:
        super().__init__()
        self.component = component

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "component": getattr(record, "component", self.component),
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
        }
        fields = {
            key: value
            for key, value in record.__dict__.items()
            if key
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "component",
            }
        }
        if fields:
            payload["fields"] = redact_mapping(fields)
        if record.exc_info:
            payload["exception"] = redact_secrets(super().formatException(record.exc_info))
        return json.dumps(payload, sort_keys=True, default=str)


def configure_component_logging(
    *,
    component: str,
    log_dir: Path | str,
    level: str = "INFO",
    retention_days: int = 7,
) -> Path:
    resolved_dir = Path(log_dir)
    try:
        resolved_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        resolved_dir = Path(tempfile.gettempdir()) / "encodr-logs"
        resolved_dir.mkdir(parents=True, exist_ok=True)
    log_path = resolved_dir / f"{component}.jsonl"
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)
    for handler in root_logger.handlers:
        if getattr(handler, "_encodr_log_path", None) == log_path.as_posix():
            return log_path
    handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        backupCount=max(1, int(retention_days)),
        encoding="utf-8",
        utc=True,
    )
    handler.setLevel(numeric_level)
    handler.setFormatter(JsonLogFormatter(component=component))
    handler._encodr_log_path = log_path.as_posix()  # type: ignore[attr-defined]
    root_logger.addHandler(handler)
    cleanup_old_logs(resolved_dir, retention_days=retention_days)
    return log_path


def cleanup_old_logs(log_dir: Path | str, *, retention_days: int = 7) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(retention_days)))
    for path in Path(log_dir).glob("*.jsonl*"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if modified < cutoff:
            try:
                path.unlink()
            except OSError:
                continue


def read_log_events(
    log_dir: Path | str,
    *,
    component: str | None = None,
    level: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    redact_paths: bool = False,
) -> list[DiagnosticLogEvent]:
    events: list[DiagnosticLogEvent] = []
    for path in sorted(_log_paths(log_dir, component=component), key=lambda item: item.name):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = _event_from_payload(payload, fallback_component=path.name.split(".", 1)[0])
            if event is None:
                continue
            if level and event.level != level.lower():
                continue
            if since is not None and _parse_timestamp(event.timestamp) < since:
                continue
            if redact_paths:
                event = _redact_event_paths(event)
            events.append(event)
    events.sort(key=lambda event: event.timestamp)
    return events[-max(1, min(limit, 1000)) :]


def build_diagnostic_bundle(
    *,
    log_dir: Path | str,
    summary: dict[str, Any],
    health: dict[str, Any],
    workers: dict[str, Any],
    jobs_recent: dict[str, Any],
    config_summary: dict[str, Any],
    since: datetime,
    redact_paths: bool,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("summary.json", _json_dump(summary, redact_paths=redact_paths))
        archive.writestr("health.json", _json_dump(health, redact_paths=redact_paths))
        archive.writestr("workers.json", _json_dump(workers, redact_paths=redact_paths))
        archive.writestr("jobs_recent.json", _json_dump(jobs_recent, redact_paths=redact_paths))
        archive.writestr("config_summary_redacted.json", _json_dump(config_summary, redact_paths=True))
        for component in ["api", "worker", "worker-agent", "system"]:
            events = read_log_events(
                log_dir,
                component=component,
                since=since,
                limit=1000,
                redact_paths=redact_paths,
            )
            archive.writestr(
                f"logs/{component}.jsonl",
                "\n".join(_json_dump(asdict(event), redact_paths=redact_paths) for event in events),
            )
    return buffer.getvalue()


def redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_PATTERN.search(str(key)):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = redact_mapping(item)
        return result
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def redact_secrets(value: str) -> str:
    cleaned = SECRET_VALUE_PATTERN.sub(r"\1\2[REDACTED]", value)
    return DSN_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]:[REDACTED]@", cleaned)


def redact_paths(value: str) -> str:
    return PATH_PATTERN.sub("[PATH]", value)


def _json_dump(payload: Any, *, redact_paths: bool) -> str:
    cleaned = redact_mapping(payload)
    if redact_paths:
        cleaned = _redact_paths_in_payload(cleaned)
    return json.dumps(cleaned, indent=2, sort_keys=True, default=str)


def _redact_paths_in_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_paths_in_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_paths_in_payload(item) for item in value]
    if isinstance(value, str):
        return redact_paths(value)
    return value


def _log_paths(log_dir: Path | str, *, component: str | None) -> list[Path]:
    root = Path(log_dir)
    if component:
        return sorted(root.glob(f"{component}.jsonl*"))
    return sorted(root.glob("*.jsonl*"))


def _event_from_payload(payload: dict[str, Any], *, fallback_component: str) -> DiagnosticLogEvent | None:
    timestamp = payload.get("timestamp")
    message = payload.get("message")
    if not isinstance(timestamp, str) or not isinstance(message, str):
        return None
    return DiagnosticLogEvent(
        timestamp=timestamp,
        level=str(payload.get("level") or "info").lower(),
        component=str(payload.get("component") or fallback_component),
        logger=str(payload.get("logger") or ""),
        message=redact_secrets(message),
        fields=redact_mapping(dict(payload.get("fields") or {})),
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _redact_event_paths(event: DiagnosticLogEvent) -> DiagnosticLogEvent:
    return DiagnosticLogEvent(
        timestamp=event.timestamp,
        level=event.level,
        component=event.component,
        logger=event.logger,
        message=redact_paths(event.message),
        fields=_redact_paths_in_payload(event.fields),
    )
