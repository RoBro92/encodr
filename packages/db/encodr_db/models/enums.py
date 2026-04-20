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


class WorkerType(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class WorkerRegistrationStatus(StrEnum):
    REGISTERED = "registered"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class WorkerHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


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


class ManualReviewDecisionType(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    HELD = "held"
    MARK_PROTECTED = "mark_protected"
    CLEAR_PROTECTED = "clear_protected"
    REPLAN_REQUESTED = "replan_requested"
    JOB_CREATED = "job_created"


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"


class AuditEventType(StrEnum):
    BOOTSTRAP_ADMIN_CREATED = "bootstrap_admin_created"
    BOOTSTRAP_ADMIN_BLOCKED = "bootstrap_admin_blocked"
    LOGIN = "login"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"
    MANUAL_REVIEW_ACTION = "manual_review_action"
    WORKER_REGISTRATION = "worker_registration"
    WORKER_HEARTBEAT_AUTH_FAILURE = "worker_heartbeat_auth_failure"
    WORKER_STATE_CHANGE = "worker_state_change"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
