from __future__ import annotations

import shutil
from enum import StrEnum
from pathlib import Path
from typing import Any

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

        if backup_path.exists():
            raise ReplacementError(
                "A backup file already exists for the source path.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                original_backup_path=backup_path,
            )
        if final_output_path != source_path and final_output_path.exists():
            raise ReplacementError(
                "A destination file already exists for the replacement target.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
            )

        source_path.rename(backup_path)
        try:
            shutil.move(staged_output_path.as_posix(), final_output_path.as_posix())
        except Exception as error:
            if backup_path.exists() and not source_path.exists():
                backup_path.rename(source_path)
            raise ReplacementError(
                "Failed to move the verified output into place.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                original_backup_path=backup_path,
                details={"error": str(error)},
            ) from error

        deleted_original_source = False
        if plan.replace.delete_replaced_source and backup_path.exists():
            backup_path.unlink()
            deleted_original_source = True

        return ReplacementResult(
            status=ReplacementStatus.SUCCEEDED,
            final_output_path=final_output_path,
            original_backup_path=None if deleted_original_source else backup_path,
            deleted_original_source=deleted_original_source,
            details={"mode": "replace_in_place"},
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
            shutil.move(staged_output_path.as_posix(), final_output_path.as_posix())
        except Exception as error:
            raise ReplacementError(
                "Failed to place the verified output alongside the source file.",
                source_path=source_path,
                staged_output_path=staged_output_path,
                final_output_path=final_output_path,
                details={"error": str(error)},
            ) from error

        return ReplacementResult(
            status=ReplacementStatus.SUCCEEDED,
            final_output_path=final_output_path,
            deleted_original_source=False,
            details={"mode": "keep_original"},
        )

    def _build_backup_path(self, source_path: Path) -> Path:
        return source_path.with_name(f"{source_path.stem}.encodr-backup{source_path.suffix}")
