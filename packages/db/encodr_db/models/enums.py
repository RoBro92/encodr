from enum import StrEnum


class FileLifecycleState(StrEnum):
    DISCOVERED = "discovered"
    PROBED = "probed"
    PLANNED = "planned"
    MANUAL_REVIEW = "manual_review"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ComplianceState(StrEnum):
    UNKNOWN = "unknown"
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    MANUAL_REVIEW = "manual_review"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    MANUAL_REVIEW = "manual_review"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class ReplacementStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"
