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


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"


class AuditEventType(StrEnum):
    BOOTSTRAP_ADMIN_CREATED = "bootstrap_admin_created"
    BOOTSTRAP_ADMIN_BLOCKED = "bootstrap_admin_blocked"
    LOGIN = "login"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
