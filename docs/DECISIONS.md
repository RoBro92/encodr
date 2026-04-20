# Decisions

## Confirmed decisions

- Project name is `encodr`.
- The tool is a private, self-hosted ingestion preparation service.
- Scope is narrow by design and does not compete with Tdarr or FileFlows on breadth.
- Backend stack is Python with FastAPI.
- Frontend stack is React with Vite.
- Persistent state uses Postgres.
- Queue and transient coordination use Redis.
- Policy is YAML-driven, not hardcoded.
- Planning must be deterministic and reviewable.
- 4K defaults are preserve-video and strip-only for unwanted languages.
- Non-4K can be skipped, remuxed, or transcoded according to policy.
- English audio and subtitles are the default retained languages.
- Forced English subtitles must always be preserved.
- Best surround audio should be preserved.
- Atmos-capable audio should be preserved where possible.
- MKV is the default output container.
- Processed files return to the original folder by default.
- Authentication is required because the app has network file access.
- Initial deployment target is Debian LXC with Docker Compose inside the LXC.
- Local worker first; remote worker support comes later.

## Open early decisions

- exact session storage approach for refresh tokens
- path discovery model for new files
- file fingerprint strategy for idempotency
- whether policy editing in the UI writes YAML directly or produces reviewed changes
