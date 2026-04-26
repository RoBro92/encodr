# Known Limitations

- Encodr is still a `v0.x` release and should be validated on disposable or representative media before real library use.
- Remote workers require shared storage access. Encodr does not copy full media files to workers.
- Worker path mappings must match the real server and worker paths.
- Windows is the most documented remote-worker target; Linux and macOS bootstrap exists but needs real-host validation in your environment.
- AMD, NVIDIA, and Intel hardware paths depend on actual driver, passthrough, container, and FFmpeg support on the worker host.
- Scheduling exists, but richer balancing, autoscaling, and cluster orchestration remain future work.
- Remote worker progress reporting is intentionally simple compared with local runtime visibility.
- In-app config editing is scoped to supported setup areas, not a generic YAML editor.
- Analytics are operational summaries, not a BI/report-builder system.
- Rich rename execution is limited even though rename templates exist.
- External artwork support is limited to local-sidecar/operational display paths.
- Automatic rollback is not implemented for failed updates; operator validation is still required.
