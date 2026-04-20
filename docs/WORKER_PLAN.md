# Worker Plan

## Responsibilities

- receive queued jobs
- run `ffprobe`
- build a deterministic plan from current policy
- execute remux or transcode actions
- verify outputs
- replace or return files safely
- update DB state and analytics

## Execution stages

1. probe source file
2. normalise metadata
3. evaluate policy
4. persist plan and job state
5. poll the next pending local job
6. execute remux or transcode if needed
7. write output to scratch space
8. probe and verify the staged output
9. place the verified output back into the source directory with a safe replacement flow
10. persist final state, verification data, and replacement outcome

## Local-first assumptions

- the first worker runs in the Debian LXC
- ffmpeg and ffprobe are available locally
- scratch space is local NVMe, not NFS
- GPU acceleration is optional and capability-driven
- the first execution loop is single-node and single-worker
- no advanced scheduling or distributed locking is included yet
- ffmpeg success alone is not final success

## Future extensions

- remote worker registration
- capability-aware queue routing
- stricter concurrency controls by worker class
