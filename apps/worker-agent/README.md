# Worker Agent

Remote worker groundwork process for Encodr. It currently handles registration, capability reporting, token handling, and secure heartbeats for future remote workers.

Current scope:

- env-based configuration loading
- registration against the API with a bootstrap secret
- worker-token persistence and heartbeat calls
- capability/host/runtime summary reporting

Not implemented yet:

- job polling
- remote execution
- delegated file access
