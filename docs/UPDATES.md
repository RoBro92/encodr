# Updates

Encodr uses a conservative command-line update flow.

The recommended install path uses the installer from `main`, while updates after install should use the local CLI.
Update checks are enabled by default for installed releases and use the Encodr GitHub release feed.

## Check for updates

```bash
encodr update-check
```

This checks the configured metadata source and tells you whether a newer release is available.

## Apply an update

```bash
encodr update --apply
```

When an update is available, Encodr will:

- download the release archive
- update the install tree
- preserve local runtime files such as `.env`, `.runtime`, and live config
- rebuild and restart the Docker stack
- run health checks afterwards

## UI behaviour

The web UI shows a modal when a newer release is available, including a short changelog summary and the root-console command to run. The UI does not apply updates itself. Updates remain a command-line operator action.

## Notes

- automatic rollback is not implemented
- update checks can be disabled
- update checks depend on a trusted version metadata source
- after updating, run `encodr doctor` if you want an extra manual check
