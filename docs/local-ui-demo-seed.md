# Local UI Demo Seed

These commands are for local/test UI design work only. They never run during install, startup, migrations, or normal worker execution.

## Seed Demo Data

Run from the Encodr checkout or LXC install root:

```bash
./encodr dev-seed-ui
```

The command replaces prior demo records under `/media/__encodr_ui_demo__`, then seeds:

- one configured local CPU worker named `Demo Local CPU Worker`
- three jobs attached to that worker: a running CPU transcode, a scheduled dry-run job, and a failed retryable interruption
- three open review items: compression safety, protected 4K preserve, and unknown-language audio
- linked tracked files, probe snapshots, plan snapshots, job progress/details, and review reasons/warnings

The media paths are realistic `/media/...` paths, but no real files are required.

## Clear Demo Data

```bash
./encodr dev-clear-ui-seed
```

This removes only the namespaced demo records. If the seed temporarily replaced an existing configured local worker, the clear command restores its previous settings.
