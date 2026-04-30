from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import threading
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.services.errors import ApiConflictError, ApiServiceError, ApiValidationError
from app.services.files import FilesService
from app.services.jobs import JobsService
from app.services.library import LibraryService, VIDEO_EXTENSIONS
from app.services.plans import PlansService
from encodr_core.config import ConfigBundle
from encodr_core.media import encodr_exclusion_reason
from encodr_db.models import BulkQueueOperation
from encodr_db.repositories import BulkQueueOperationRepository

logger = logging.getLogger("encodr.bulk_queue")

BULK_QUEUE_BATCH_SIZE = 25
MAX_RESULT_ITEMS = 100


@dataclass(slots=True)
class BulkQueueSelection:
    scope: str
    files: list[Path]
    skipped_items: list[dict[str, str]]
    failed_items: list[dict[str, str]]


class BulkQueueService:
    def __init__(
        self,
        *,
        config_bundle: ConfigBundle,
        session_factory: sessionmaker[Session],
        probe_client_factory,
    ) -> None:
        self.config_bundle = config_bundle
        self.session_factory = session_factory
        self.probe_client_factory = probe_client_factory

    def create_operation(
        self,
        session: Session,
        *,
        payload: Any,
        batch_size: int = BULK_QUEUE_BATCH_SIZE,
    ) -> tuple[BulkQueueOperation, bool]:
        operation_payload = _normalise_operation_payload(payload, batch_size=batch_size)
        selection_hash = _selection_hash(operation_payload)
        repository = BulkQueueOperationRepository(session)
        existing = repository.get_active_by_selection_hash(selection_hash)
        if existing is not None:
            return existing, False
        active = repository.get_active()
        if active is not None:
            raise ApiConflictError("Another bulk queue operation is already running.")
        scope = _selection_scope(operation_payload["selection"])
        operation = repository.create_operation(
            selection_hash=selection_hash,
            scope=scope,
            payload=operation_payload,
            batch_size=batch_size,
        )
        return operation, True

    def process_operation(self, operation_id: str) -> None:
        state = {
            "queued": 0,
            "skipped": 0,
            "blocked": 0,
            "failed": 0,
            "items": [],
        }
        try:
            with self.session_factory() as session:
                operation = self._get_operation(session, operation_id)
                BulkQueueOperationRepository(session).mark_running(operation, status_text="Scanning selection")
                session.commit()

            selection = self._resolve_selection(operation_id)
            state["skipped"] = len(selection.skipped_items)
            state["failed"] = len(selection.failed_items)
            state["items"] = [*selection.skipped_items, *selection.failed_items][:MAX_RESULT_ITEMS]
            total_expected = len(selection.files) + int(state["skipped"]) + int(state["failed"])
            batches = _chunks(selection.files, self._operation_batch_size(operation_id))
            total_batches = len(batches)
            self._update_operation(
                operation_id,
                stage="itemising_files",
                status_text="Itemising files",
                total_expected=total_expected,
                discovered_count=total_expected,
                skipped_count=int(state["skipped"]),
                failed_count=int(state["failed"]),
                total_batches=total_batches,
                result_summary={"items": list(state["items"])},
            )

            if total_expected == 0:
                self._finish_operation(
                    operation_id,
                    status="completed",
                    stage="completed",
                    status_text="No processable media files were found.",
                    state=state,
                )
                return

            payload = self._operation_payload(operation_id)
            options = dict(payload["options"])
            for batch_number, batch in enumerate(batches, start=1):
                if self._cancel_requested(operation_id):
                    self._finish_operation(
                        operation_id,
                        status="cancelled",
                        stage="completed",
                        status_text="Bulk queue operation was cancelled.",
                        state=state,
                    )
                    return
                self._update_operation(
                    operation_id,
                    stage="sending_to_queue",
                    status_text=f"Adding batch {batch_number} of {total_batches}",
                    current_batch=batch_number,
                    total_batches=total_batches,
                    queued_count=int(state["queued"]),
                    skipped_count=int(state["skipped"]),
                    blocked_count=int(state["blocked"]),
                    failed_count=int(state["failed"]),
                )
                for source_path in batch:
                    if self._cancel_requested(operation_id):
                        self._finish_operation(
                            operation_id,
                            status="cancelled",
                            stage="completed",
                            status_text="Bulk queue operation was cancelled.",
                            state=state,
                        )
                        return
                    item = self._queue_one_file(source_path, options)
                    status = item["status"]
                    if status == "created":
                        state["queued"] = int(state["queued"]) + 1
                    elif status == "blocked":
                        state["blocked"] = int(state["blocked"]) + 1
                    elif status == "skipped":
                        state["skipped"] = int(state["skipped"]) + 1
                    else:
                        state["failed"] = int(state["failed"]) + 1
                    if len(state["items"]) < MAX_RESULT_ITEMS:
                        state["items"].append(item)
                    self._update_operation(
                        operation_id,
                        queued_count=int(state["queued"]),
                        skipped_count=int(state["skipped"]),
                        blocked_count=int(state["blocked"]),
                        failed_count=int(state["failed"]),
                        result_summary={"items": list(state["items"])},
                    )

            self._finish_operation(
                operation_id,
                status="completed",
                stage="completed",
                status_text="Completed",
                state=state,
            )
        except Exception as error:  # noqa: BLE001
            logger.exception("bulk queue operation failed", extra={"operation_id": operation_id})
            try:
                self._finish_operation(
                    operation_id,
                    status="failed",
                    stage="completed",
                    status_text="Bulk queue operation failed.",
                    state=state,
                    error_summary=str(error),
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist bulk queue failure", extra={"operation_id": operation_id})

    def _resolve_selection(self, operation_id: str) -> BulkQueueSelection:
        payload = self._operation_payload(operation_id)
        selection = dict(payload["selection"])
        library = LibraryService(config_bundle=self.config_bundle)
        skipped_items: list[dict[str, str]] = []
        failed_items: list[dict[str, str]] = []
        files: list[Path] = []

        self._update_operation(operation_id, stage="scanning_selection", status_text="Scanning selection")
        if selection.get("source_path"):
            self._append_selected_path(selection["source_path"], library, files, skipped_items, failed_items)
            scope = "file"
        elif selection.get("folder_path"):
            scope = "folder"
            folder = library.resolve_directory(selection["folder_path"])
            self._update_operation(operation_id, stage="itemising_files", status_text="Itemising files")
            for item in folder.rglob("*"):
                if item.name.startswith(".") or item.is_dir() or item.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                self._append_selected_path(item.as_posix(), library, files, skipped_items, failed_items)
        else:
            scope = "selection"
            for raw_path in selection.get("selected_paths", []):
                self._append_selected_path(raw_path, library, files, skipped_items, failed_items)

        deduplicated: dict[str, Path] = {path.as_posix(): path for path in files}
        return BulkQueueSelection(
            scope=scope,
            files=list(deduplicated.values()),
            skipped_items=skipped_items,
            failed_items=failed_items,
        )

    def _append_selected_path(
        self,
        raw_path: str,
        library: LibraryService,
        files: list[Path],
        skipped_items: list[dict[str, str]],
        failed_items: list[dict[str, str]],
    ) -> None:
        try:
            candidate = Path(raw_path).expanduser()
            reason = encodr_exclusion_reason(candidate, scratch_dir=self.config_bundle.app.scratch_dir)
            if reason is not None:
                skipped_items.append({"source_path": raw_path, "status": "skipped", "message": reason})
                return
            resolved = library.resolve_file(raw_path)
            if resolved.suffix.lower() not in VIDEO_EXTENSIONS:
                skipped_items.append({"source_path": raw_path, "status": "skipped", "message": "Only media video files can be queued."})
                return
            files.append(resolved)
        except ApiServiceError as error:
            failed_items.append({"source_path": raw_path, "status": "failed", "message": str(error)})

    def _queue_one_file(self, source_path: Path, options: dict[str, Any]) -> dict[str, str]:
        with self.session_factory() as session:
            try:
                plans_service = PlansService(
                    config_bundle=self.config_bundle,
                    files_service=FilesService(
                        config_bundle=self.config_bundle,
                        probe_client_factory=self.probe_client_factory,
                    ),
                )
                tracked_file, _probe_snapshot, plan_snapshot = plans_service.plan_file(
                    session,
                    source_path=source_path.as_posix(),
                )
                results = JobsService().create_batch_jobs(
                    session,
                    planned_targets=[(source_path.as_posix(), tracked_file, plan_snapshot)],
                    preferred_worker_id=options.get("preferred_worker_id"),
                    pinned_worker_id=options.get("pinned_worker_id"),
                    preferred_backend_override=options.get("preferred_backend_override"),
                    schedule_windows=options.get("schedule_windows") or None,
                    backup_policy=str(options.get("backup_policy") or "keep"),
                )
                result = results[0]
                session.commit()
                return {
                    "source_path": source_path.as_posix(),
                    "status": str(result["status"]),
                    "message": str(result["message"] or ""),
                }
            except ApiServiceError as error:
                session.rollback()
                return {
                    "source_path": source_path.as_posix(),
                    "status": "failed",
                    "message": str(error),
                }
            except Exception as error:  # noqa: BLE001
                session.rollback()
                logger.exception("bulk queue item failed", extra={"source_path": source_path.as_posix()})
                return {
                    "source_path": source_path.as_posix(),
                    "status": "failed",
                    "message": str(error),
                }

    def _operation_payload(self, operation_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            operation = self._get_operation(session, operation_id)
            return dict(operation.payload or {})

    def _operation_batch_size(self, operation_id: str) -> int:
        with self.session_factory() as session:
            return max(1, int(self._get_operation(session, operation_id).batch_size or BULK_QUEUE_BATCH_SIZE))

    def _cancel_requested(self, operation_id: str) -> bool:
        with self.session_factory() as session:
            operation = self._get_operation(session, operation_id)
            return operation.status == "cancelling"

    def _update_operation(self, operation_id: str, **values: Any) -> None:
        with self.session_factory() as session:
            operation = self._get_operation(session, operation_id)
            BulkQueueOperationRepository(session).update_progress(operation, **values)
            session.commit()

    def _finish_operation(
        self,
        operation_id: str,
        *,
        status: str,
        stage: str,
        status_text: str,
        state: dict[str, Any],
        error_summary: str | None = None,
    ) -> None:
        with self.session_factory() as session:
            operation = self._get_operation(session, operation_id)
            repository = BulkQueueOperationRepository(session)
            repository.update_progress(
                operation,
                queued_count=int(state.get("queued", 0)),
                skipped_count=int(state.get("skipped", 0)),
                blocked_count=int(state.get("blocked", 0)),
                failed_count=int(state.get("failed", 0)),
            )
            repository.finish(
                operation,
                status=status,
                stage=stage,
                status_text=status_text,
                result_summary={
                    "items": list(state.get("items", []))[:MAX_RESULT_ITEMS],
                    "queued_count": int(state.get("queued", 0)),
                    "skipped_count": int(state.get("skipped", 0)),
                    "blocked_count": int(state.get("blocked", 0)),
                    "failed_count": int(state.get("failed", 0)),
                },
                error_summary=error_summary,
            )
            session.commit()

    @staticmethod
    def _get_operation(session: Session, operation_id: str) -> BulkQueueOperation:
        operation = BulkQueueOperationRepository(session).get_by_id(operation_id)
        if operation is None:
            raise ApiValidationError("Bulk queue operation could not be found.")
        return operation


class BulkQueueExecutor:
    def __init__(self, service: BulkQueueService) -> None:
        self.service = service
        self._lock = threading.Lock()
        self._running_operation_ids: set[str] = set()

    def start(self, operation_id: str) -> None:
        with self._lock:
            if operation_id in self._running_operation_ids:
                return
            self._running_operation_ids.add(operation_id)
        thread = threading.Thread(
            target=self._run_and_clear,
            args=(operation_id,),
            name=f"encodr-bulk-queue-{operation_id[:8]}",
            daemon=True,
        )
        thread.start()

    def _run_and_clear(self, operation_id: str) -> None:
        try:
            self.service.process_operation(operation_id)
        finally:
            with self._lock:
                self._running_operation_ids.discard(operation_id)


def _normalise_operation_payload(payload: Any, *, batch_size: int) -> dict[str, Any]:
    selection = {
        "source_path": getattr(payload, "source_path", None),
        "folder_path": getattr(payload, "folder_path", None),
        "selected_paths": list(getattr(payload, "selected_paths", []) or []),
    }
    provided = sum(bool(value) for value in [selection["source_path"], selection["folder_path"], selection["selected_paths"]])
    if provided != 1:
        raise ApiValidationError("Provide exactly one of source_path, folder_path, or selected_paths.")
    options = {
        "preferred_worker_id": getattr(payload, "preferred_worker_id", None),
        "pinned_worker_id": getattr(payload, "pinned_worker_id", None),
        "preferred_backend_override": getattr(payload, "preferred_backend_override", None),
        "schedule_windows": [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in (getattr(payload, "schedule_windows", []) or [])
        ],
        "backup_policy": getattr(payload, "backup_policy", "keep") or "keep",
    }
    return {
        "selection": selection,
        "options": options,
        "batch_size": batch_size,
    }


def _selection_scope(selection: dict[str, Any]) -> str:
    if selection.get("source_path"):
        return "file"
    if selection.get("folder_path"):
        return "folder"
    return "selection"


def _selection_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _chunks(items: list[Path], size: int) -> list[list[Path]]:
    if not items:
        return []
    return [items[index:index + size] for index in range(0, len(items), size)]
