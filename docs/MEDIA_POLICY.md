# Media Policy

Encodr uses explicit processing rules to decide what should happen to a file. Rules are deterministic and operator-visible, so the same file and ruleset should produce the same plan.

## Rulesets

Current user-facing rulesets:

- Movies
- Movies 4K
- TV
- TV 4K

Rules cover languages, subtitle handling, surround/Atmos preservation, codecs, containers, 4K handling, compression safety, and output behaviour.

## Decisions

Plans can result in:

- `skip`
- `remux`
- `transcode`
- `manual_review`

Low-confidence, ambiguous, protected, or unsafe cases should go to manual review rather than being processed automatically.

## Non-4K Defaults

Non-4K files may be skipped, remuxed, transcoded, or sent to manual review. `skip` is used only when the file already appears compliant. `remux` is used when container or stream cleanup is enough. `transcode` is used when video policy requires it.

Compression safety is based on video-size reduction, not savings produced only by stripping audio or subtitles.

## 4K Defaults

4K defaults are conservative:

- preserve original video
- preserve selected English audio and subtitles
- strip non-English audio/subtitles where rules allow
- do not transcode 4K under the default strip-only mode
- require manual review when expectations cannot be satisfied confidently

HDR, Dolby Vision-like, Atmos-capable, and preserve-oriented files may be marked protected.

## Audio And Subtitles

Defaults prefer English audio and subtitles. Encodr preserves forced English subtitles, keeps preferred-language tracks according to policy, and preserves stronger surround/Atmos-capable audio where visible.

Commentary, hearing-impaired subtitles, undetermined languages, and ambiguous forced-subtitle metadata are handled conservatively and may create warnings or manual review.

## Dry Runs

Dry runs analyse files through the planning path without modifying media. Use dry runs before enabling watched jobs or queueing work across a real library.

## Output And Replacement

Processing writes to scratch first. FFmpeg success is not final success. A job is only successful after staged output is verified and placement/replacement succeeds.

Original deletion remains conservative and policy-driven.

## Current Caveats

- rich rename execution is still limited even though rename templates exist
- external artwork integration is not a full metadata/artwork system
- hardware-specific processing should be validated on the real worker host before relying on it
