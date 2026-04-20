from enum import StrEnum


class JobDecision(StrEnum):
    SKIP = "skip"
    REMUX = "remux"
    TRANSCODE = "transcode"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

