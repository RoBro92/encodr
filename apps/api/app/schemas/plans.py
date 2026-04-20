from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from encodr_db.models import PlanSnapshot, ProbeSnapshot


class ProbeSnapshotSummaryResponse(BaseModel):
    id: str
    tracked_file_id: str
    schema_version: int
    created_at: datetime
    file_name: str | None = None
    format_name: str | None = None
    duration_seconds: float | None = None
    size_bytes: int | None = None
    video_stream_count: int = 0
    audio_stream_count: int = 0
    subtitle_stream_count: int = 0
    is_4k: bool = False

    @classmethod
    def from_snapshot(cls, snapshot: ProbeSnapshot) -> "ProbeSnapshotSummaryResponse":
        payload = snapshot.payload
        container = payload.get("container", {})
        return cls(
            id=snapshot.id,
            tracked_file_id=snapshot.tracked_file_id,
            schema_version=snapshot.schema_version,
            created_at=snapshot.created_at,
            file_name=container.get("file_name"),
            format_name=container.get("format_name"),
            duration_seconds=container.get("duration_seconds"),
            size_bytes=container.get("size_bytes"),
            video_stream_count=len(payload.get("video_streams", [])),
            audio_stream_count=len(payload.get("audio_streams", [])),
            subtitle_stream_count=len(payload.get("subtitle_streams", [])),
            is_4k=bool(payload.get("is_4k", False)),
        )


class ProbeSnapshotDetailResponse(ProbeSnapshotSummaryResponse):
    payload: dict[str, Any]

    @classmethod
    def from_snapshot(cls, snapshot: ProbeSnapshot) -> "ProbeSnapshotDetailResponse":
        summary = ProbeSnapshotSummaryResponse.from_snapshot(snapshot)
        return cls(**summary.model_dump(), payload=snapshot.payload)


class PlanSnapshotSummaryResponse(BaseModel):
    id: str
    tracked_file_id: str
    probe_snapshot_id: str
    action: str
    confidence: str
    policy_version: int
    profile_name: str | None = None
    is_already_compliant: bool
    should_treat_as_protected: bool
    created_at: datetime
    reason_codes: list[str]
    warning_codes: list[str]
    selected_audio_stream_indices: list[int]
    selected_subtitle_stream_indices: list[int]

    @classmethod
    def from_snapshot(cls, snapshot: PlanSnapshot) -> "PlanSnapshotSummaryResponse":
        selected_streams = snapshot.payload.get("selected_streams", {})
        return cls(
            id=snapshot.id,
            tracked_file_id=snapshot.tracked_file_id,
            probe_snapshot_id=snapshot.probe_snapshot_id,
            action=snapshot.action.value,
            confidence=snapshot.confidence.value,
            policy_version=snapshot.policy_version,
            profile_name=snapshot.profile_name,
            is_already_compliant=snapshot.is_already_compliant,
            should_treat_as_protected=snapshot.should_treat_as_protected,
            created_at=snapshot.created_at,
            reason_codes=[reason.get("code", "") for reason in snapshot.reasons],
            warning_codes=[warning.get("code", "") for warning in snapshot.warnings],
            selected_audio_stream_indices=selected_streams.get("audio_stream_indices", []),
            selected_subtitle_stream_indices=selected_streams.get("subtitle_stream_indices", []),
        )


class PlanSnapshotDetailResponse(PlanSnapshotSummaryResponse):
    reasons: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    selected_streams: dict[str, Any]
    payload: dict[str, Any]

    @classmethod
    def from_snapshot(cls, snapshot: PlanSnapshot) -> "PlanSnapshotDetailResponse":
        summary = PlanSnapshotSummaryResponse.from_snapshot(snapshot)
        return cls(
            **summary.model_dump(),
            reasons=snapshot.reasons,
            warnings=snapshot.warnings,
            selected_streams=snapshot.selected_streams,
            payload=snapshot.payload,
        )
