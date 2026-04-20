# Renaming Rules

## Goal

Renaming must remain Plex-friendly and predictable. Templates should be configurable, but defaults should map cleanly to common Plex naming expectations.

## Default direction

- Movies: `Title (Year)`
- Episodes: `Series Title/Season NN/Series Title - sNNeNN - Episode Title`
- Output container defaults to `.mkv`

## Template principles

- use metadata already known from the file or provided alongside it
- sanitise filesystem-hostile characters
- avoid overly clever transformations
- preserve human readability
- keep the template system explicit and reviewable

## Future template fields

- `title`
- `year`
- `series_title`
- `season_number`
- `season_number_padded`
- `episode_number`
- `episode_number_padded`
- `episode_title`
- `edition`
- `video_codec`
- `resolution_label`

## Operational rules

- renaming should be optional per policy
- return-to-source-folder remains the default even when renaming is enabled
- naming changes should be logged for reviewability

