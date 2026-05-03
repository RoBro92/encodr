from __future__ import annotations

import errno
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import Field

from encodr_core.config.base import ConfigModel
from encodr_core.planning import ProcessingPlan
from encodr_core.replacement.errors import ReplacementError


class ReplacementStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class ReplacementResult(ConfigModel):
    status: ReplacementStatus
    final_output_path: Path | None = None
    original_backup_path: Path | None = None
    deleted_original_source: bool = False
    failure_message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def not_required(cls) -> "ReplacementResult":
        return cls(status=ReplacementStatus.NOT_REQUIRED)


@dataclass(frozen=True, slots=True)
class _OutputMoveResult:
    details: dict[str, Any]


class ReplacementService:
    def place_verified_output(
        self,
        *,
        source_path: Path | str,
        staged_output_path: Path | str,
        plan: ProcessingPlan,
    ) -> ReplacementResult:
        resolved_source = Path(source_path)
        resolved_staged = Path(staged_output_path)

        if not resolved_staged.exists():
            return ReplacementResult(
                status=ReplacementStatus.FAILED,
                failure_message="The staged output file does not exist.",
                details={"staged_output_path": resolved_staged.as_posix()},
            )

        try:
            if plan.replace.in_place:
                return self._replace_in_place(
                    source_path=resolved_source,
                    staged_output_path=resolved_staged,
                    plan=plan,
                )
            return self._place_alongside_original(
                source_path=resolved_source,
                staged_output_path=resolved_staged,
                plan=plan,
            )
        except ReplacementError as error:
            return ReplacementResult(
                status=ReplacementStatus.FAILED,
                final_output_path=error.final_output_path,
                original_backup_path=error.original_backup_path,
                failure_message=error.message,
                details=error.details,
            )

    def _replace_in_place(
        self,
        *,
        source_path: Path,
        staged_output_path: Path,
        plan: ProcessingPlan,
    ) -> ReplacementResult:
        if not source_path.exists():
            raise ReplacementError(
                "The source file does not exist for in-place replacement.",
                source_path=source_path,
                staged_output_path=staged_output_path,
            )

        final_output_path = source_path.with_suffix(f".{plan.container.target_container.value}")
        backup_path = self._build_backup_path(source_path)
        existing_backup_strategy = plan.replace.existing_backup_strategy
        backup_exists = backup_path.exists()

        if backup_exists and existing_backup_strategy == "fail":
            raise ReplacementError(
                "A backup file already exists for the source path.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                original_backup_path=backup_path,
                details={
                    "failure_code": "backup_already_exists",
                    "existing_backup_strategy": existing_backup_strategy,
                },
            )
        if not backup_exists and existing_backup_strategy == "keep_existing_backup":
            raise ReplacementError(
                "A backup file must already exist before keeping the original backup.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                original_backup_path=backup_path,
                details={
                    "failure_code": "backup_missing_for_keep_existing",
                    "existing_backup_strategy": existing_backup_strategy,
                },
            )
        if final_output_path != source_path and final_output_path.exists():
            raise ReplacementError(
                "A destination file already exists for the replacement target.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
            )

        replaced_backup_path: Path | None = None
        if backup_exists and existing_backup_strategy == "replace_backup":
            replaced_backup_path = _temporary_replaced_backup_path(backup_path)
            try:
                backup_path.rename(replaced_backup_path)
            except OSError as error:
                raise ReplacementError(
                    "Failed to move the existing backup aside before replacement.",
                    source_path=source_path,
                    staged_output_path=staged_output_path,
                    final_output_path=final_output_path,
                    original_backup_path=backup_path,
                    details=_replacement_failure_details(
                        operation="move_existing_backup_aside",
                        error=error,
                        source_path=source_path,
                        staged_output_path=staged_output_path,
                        final_output_path=final_output_path,
                        original_backup_path=backup_path,
                    ),
                ) from error

        create_new_backup = existing_backup_strategy != "keep_existing_backup"
        if create_new_backup:
            try:
                source_path.rename(backup_path)
            except OSError as error:
                details = _replacement_failure_details(
                    operation="move_source_to_backup",
                    error=error,
                    source_path=source_path,
                    staged_output_path=staged_output_path,
                    final_output_path=final_output_path,
                    original_backup_path=backup_path,
                )
                _restore_replaced_backup(
                    replaced_backup_path=replaced_backup_path,
                    backup_path=backup_path,
                    details=details,
                )
                raise ReplacementError(
                    "Failed to move the source file to its backup path.",
                    source_path=source_path,
                    staged_output_path=staged_output_path,
                    final_output_path=final_output_path,
                    original_backup_path=backup_path,
                    details=details,
                ) from error
        try:
            move_result = _move_generated_output(staged_output_path, final_output_path)
        except Exception as error:
            details = _replacement_failure_details(
                operation="move_verified_output_into_place",
                error=error,
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                original_backup_path=backup_path,
            )
            if create_new_backup and backup_path.exists() and not source_path.exists():
                try:
                    backup_path.rename(source_path)
                except OSError as rollback_error:
                    details["rollback_error"] = str(rollback_error)
                    details["rollback_errno"] = rollback_error.errno
                    details["source_exists_after_rollback"] = source_path.exists()
                    details["backup_exists_after_rollback"] = backup_path.exists()
                    details["staged_output_exists_after_rollback"] = staged_output_path.exists()
                else:
                    details["rollback_succeeded"] = True
                    details["source_exists_after_rollback"] = source_path.exists()
                    details["backup_exists_after_rollback"] = backup_path.exists()
                    details["staged_output_exists_after_rollback"] = staged_output_path.exists()
            _restore_replaced_backup(
                replaced_backup_path=replaced_backup_path,
                backup_path=backup_path,
                details=details,
            )
            raise ReplacementError(
                "Failed to move the verified output into place.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                original_backup_path=backup_path,
                details=details,
            ) from error

        deleted_original_source = False
        success_details = {
            "mode": "replace_in_place",
            "existing_backup_strategy": existing_backup_strategy,
            **move_result.details,
        }
        if create_new_backup and plan.replace.delete_replaced_source and backup_path.exists():
            try:
                backup_path.unlink()
                deleted_original_source = True
            except OSError as error:
                _delete_replaced_backup_temp(
                    replaced_backup_path=replaced_backup_path,
                    source_path=source_path,
                    staged_output_path=staged_output_path,
                    final_output_path=final_output_path,
                    backup_path=backup_path,
                    details=success_details,
                )
                return ReplacementResult(
                    status=ReplacementStatus.SUCCEEDED,
                    final_output_path=final_output_path,
                    original_backup_path=backup_path,
                    deleted_original_source=False,
                    details={
                        **success_details,
                        "backup_delete_failed": True,
                        **_replacement_failure_details(
                            operation="delete_replaced_source_backup",
                            error=error,
                            source_path=source_path,
                            staged_output_path=staged_output_path,
                            final_output_path=final_output_path,
                            original_backup_path=backup_path,
                        ),
                    },
                )

        _delete_replaced_backup_temp(
            replaced_backup_path=replaced_backup_path,
            source_path=source_path,
            staged_output_path=staged_output_path,
            final_output_path=final_output_path,
            backup_path=backup_path,
            details=success_details,
        )
        return ReplacementResult(
            status=ReplacementStatus.SUCCEEDED,
            final_output_path=final_output_path,
            original_backup_path=None if deleted_original_source else backup_path,
            deleted_original_source=deleted_original_source,
            details=success_details,
        )

    def _place_alongside_original(
        self,
        *,
        source_path: Path,
        staged_output_path: Path,
        plan: ProcessingPlan,
    ) -> ReplacementResult:
        final_output_path = source_path.with_name(
            f"{source_path.stem}.encodr.{plan.container.target_container.value}"
        )
        if final_output_path.exists():
            raise ReplacementError(
                "A destination file already exists for the placed output.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
            )

        try:
            move_result = _move_generated_output(staged_output_path, final_output_path)
        except Exception as error:
            raise ReplacementError(
                "Failed to place the verified output alongside the source file.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                details=_replacement_failure_details(
                    operation="place_verified_output_alongside_source",
                    error=error,
                    source_path=source_path,
                    staged_output_path=staged_output_path,
                    final_output_path=final_output_path,
                    original_backup_path=None,
                ),
            ) from error

        return ReplacementResult(
            status=ReplacementStatus.SUCCEEDED,
            final_output_path=final_output_path,
            deleted_original_source=False,
            details={"mode": "keep_original", **move_result.details},
        )

    def _build_backup_path(self, source_path: Path) -> Path:
        return source_path.with_name(f"{source_path.stem}.encodr-backup{source_path.suffix}")


def _move_generated_output(staged_output_path: Path, final_output_path: Path) -> _OutputMoveResult:
    try:
        staged_output_path.replace(final_output_path)
        return _OutputMoveResult(details={"move_strategy": "rename"})
    except OSError as error:
        if getattr(error, "errno", None) != errno.EXDEV:
            raise
        cross_device_details = {
            "move_strategy": "copyfile",
            "cross_device_errno": error.errno,
            "cross_device_message": str(error),
        }

    shutil.copyfile(staged_output_path, final_output_path)
    try:
        staged_output_path.unlink()
    except OSError as cleanup_error:
        cross_device_details["staged_cleanup_failed"] = True
        cross_device_details["staged_cleanup_errno"] = cleanup_error.errno
        cross_device_details["staged_cleanup_error"] = str(cleanup_error)
    return _OutputMoveResult(details=cross_device_details)


def _temporary_replaced_backup_path(backup_path: Path) -> Path:
    while True:
        candidate = backup_path.with_name(f"{backup_path.name}.replacing-{uuid4().hex}.tmp")
        if not candidate.exists():
            return candidate


def _restore_replaced_backup(
    *,
    replaced_backup_path: Path | None,
    backup_path: Path,
    details: dict[str, Any],
) -> None:
    if replaced_backup_path is None:
        return
    details["replaced_backup_temp_path"] = replaced_backup_path.as_posix()
    if not replaced_backup_path.exists():
        details["replaced_backup_temp_exists_after_rollback"] = False
        return
    if backup_path.exists():
        details["replaced_backup_restore_blocked"] = True
        details["backup_exists_after_replaced_backup_restore"] = True
        return
    try:
        replaced_backup_path.rename(backup_path)
    except OSError as rollback_error:
        details["replaced_backup_restore_error"] = str(rollback_error)
        details["replaced_backup_restore_errno"] = rollback_error.errno
    else:
        details["replaced_backup_restore_succeeded"] = True
    details["replaced_backup_temp_exists_after_rollback"] = replaced_backup_path.exists()
    details["backup_exists_after_replaced_backup_restore"] = backup_path.exists()


def _delete_replaced_backup_temp(
    *,
    replaced_backup_path: Path | None,
    source_path: Path,
    staged_output_path: Path,
    final_output_path: Path,
    backup_path: Path,
    details: dict[str, Any],
) -> None:
    if replaced_backup_path is None or not replaced_backup_path.exists():
        return
    try:
        replaced_backup_path.unlink()
    except OSError as error:
        details["replaced_backup_delete_failed"] = True
        details.update(
            _replacement_failure_details(
                operation="delete_replaced_existing_backup",
                error=error,
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                original_backup_path=backup_path,
            )
        )
        details["replaced_backup_temp_path"] = replaced_backup_path.as_posix()
    else:
        details["replaced_existing_backup_deleted"] = True


def _replacement_failure_details(
    *,
    operation: str,
    error: BaseException,
    source_path: Path,
    staged_output_path: Path,
    final_output_path: Path | None,
    original_backup_path: Path | None,
) -> dict[str, Any]:
    error_number = getattr(error, "errno", None)
    return {
        "operation": operation,
        "source_path": source_path.as_posix(),
        "staged_output_path": staged_output_path.as_posix(),
        "final_output_path": final_output_path.as_posix() if final_output_path is not None else None,
        "original_backup_path": original_backup_path.as_posix() if original_backup_path is not None else None,
        "errno": error_number,
        "exception_type": type(error).__name__,
        "exception_message": str(error),
        "source_exists": source_path.exists(),
        "staged_output_exists": staged_output_path.exists(),
        "backup_exists": original_backup_path.exists() if original_backup_path is not None else None,
        "permission_hint": (
            "The destination filesystem denied access. Check NAS share ownership, group membership, and write permissions."
            if error_number in {errno.EACCES, errno.EPERM}
            else None
        ),
    }
