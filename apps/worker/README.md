# Worker App

Local execution service for probing files, building deterministic plans, executing remux or transcode jobs, and verifying outputs before safe replacement.

Current scope:

- local job polling and run-once execution
- ffmpeg command execution through shared execution helpers
- staged-output verification and safe placement flow
- queue/health integration through the shared runtime layer
