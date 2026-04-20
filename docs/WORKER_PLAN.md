# Worker Plan

## Local worker responsibilities

- probe source files when asked
- consume persisted plans/jobs
- run local ffmpeg work for remux/transcode
- write outputs to scratch
- verify staged outputs
- place verified outputs safely back into the source directory
- persist execution, verification, replacement, and analytics outcomes

## Local execution stages

1. load the tracked file, latest probe/plan, and job
2. map the plan to ffmpeg execution intent
3. execute locally when the action is `remux` or `transcode`
4. verify the staged output
5. perform safe placement/replacement
6. persist final job/file state

## Manual review interaction

- `manual_review` jobs do not execute automatically
- protected files remain visible and explicit
- review-driven job creation is append-only and operator-controlled

## Operational health

- local worker status includes queue, binaries, last run, and self-test
- health is surfaced through API and UI

## Remote worker groundwork

- remote workers can register and heartbeat
- remote workers declare capabilities explicitly
- remote workers appear in inventory and can be enabled/disabled
- remote workers do not execute jobs yet

## Still out of scope

- remote job polling
- remote execution protocol
- advanced routing/balancing
- cluster-wide orchestration
