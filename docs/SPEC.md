# Specification

## Problem statement

Media libraries often contain files that are technically usable but undesirable for a long-term Plex-style library because they include the wrong languages, poor naming, unnecessary subtitles, or codecs that do not fit the target library strategy.

`encodr` addresses that gap by preparing files before ingestion through explicit policy and safe execution.

## Functional requirements

- Inspect media streams with `ffprobe`
- Build internal media models from probe output
- Load YAML configuration and profiles
- Distinguish 4K and non-4K policy paths
- Support `skip`, `remux`, and `transcode` decisions for non-4K files
- Support strip-only defaults for 4K files
- Preserve English audio and subtitles according to policy
- Always preserve forced English subtitles
- Preserve best surround audio and Atmos-capable audio where possible
- Default output container to MKV
- Return processed files to the source folder by default
- Record processed-file state and policy version
- Expose API and UI for operations, review, and analytics

## Non-functional requirements

- deterministic decisions
- reviewable rule application
- safe replacement flow
- typed Python code
- clean module boundaries
- deployable in a private Debian LXC environment

## Explicit non-goals

- downloader automation
- media server administration
- general-purpose transcoding farm behaviour
- replacing Tdarr or FileFlows in breadth

