# Renaming Rules

## Goal

Naming should remain Plex-friendly, predictable, and policy-driven.

## Current state

- policy models include movie and episode templates
- replacement flow currently stays conservative and source-path oriented
- advanced rich rename generation is not yet a major execution feature

## Default template direction

- Movies: `Title (Year)`
- Episodes: `Series Title/Season NN/Series Title - sNNeNN - Episode Title`
- default extension/container: `.mkv`

## Principles

- explicit template fields
- filesystem-safe output
- human-readable names
- no hidden or clever transformations
- naming actions should remain reviewable

## Future work

- richer metadata-backed filename generation
- edition/resolution/template variables
- stronger rename preview in the UI
