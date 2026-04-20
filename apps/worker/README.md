# Worker App

Local execution service for probing files, building deterministic plans, executing remux or transcode jobs, and verifying outputs before safe replacement.

Current scope:

- boot a placeholder worker process
- reserve executor, probe, planner, and verification module boundaries
- keep orchestration thin so later milestones can move logic into shared packages

