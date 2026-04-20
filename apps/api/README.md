# API App

FastAPI service for Encodr authentication, operational control, analytics, manual review, worker inventory, and sanitised configuration visibility.

Current scope:

- bootstrap-admin auth, login, logout, refresh, and current-user routes
- files/jobs/review/analytics/system/config endpoints
- local worker run-once and self-test control
- remote worker register/heartbeat groundwork plus worker inventory
- shared service-layer wiring over `encodr_core` and `encodr_db`

Business logic is expected to live primarily in shared packages rather than directly in this application layer.
