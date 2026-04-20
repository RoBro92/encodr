# Updates

## Current model

Encodr uses a simple update-check and archive-install model suitable for internal use.

- the current version comes from the root `VERSION` file
- the API and UI expose the running version
- update checks read version metadata from a configured source
- the UI shows update availability, but does not install updates
- the root CLI can check and apply an update archive

## Metadata expectations

The configured update metadata source should provide a JSON object containing at least:

- `latest_version`
- optional `channel`
- optional `download_url`
- optional `release_notes_url`

## CLI flow

```bash
encodr update-check
encodr update
encodr update --apply
```

`encodr update --apply`:
- checks metadata
- downloads the release archive
- syncs the release tree into the install root
- preserves local `.env`, runtime state, and live config files
- rebuilds/restarts the Compose stack
- runs `encodr doctor`

## Safety notes

- update checks can be disabled
- no secrets are returned through update endpoints
- the web UI is read-only for updates
- automatic rollback is not implemented yet
- operators should review `CHANGELOG.md` and run health checks after an update

## Out of scope

- package-repository distribution
- automatic merge-to-main or tagging
- in-app self-updating from the browser
