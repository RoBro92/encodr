# Media Policy

## Intent

Policy must be explicit, YAML-driven, and deterministic. The same file under the same policy version should always produce the same plan.

## Non-4K behaviour

- Non-4K content may be skipped, remuxed, or transcoded according to policy.
- The decision must be made from declared rules, not implicit code paths.
- Transcoding is allowed for non-4K where the policy says it is acceptable.
- MKV is the default output container unless a future profile opts out.
- Files that already comply with the effective policy should be skipped.
- Files that only need stream or container clean-up should be remuxed.
- Files that need codec or video-policy changes should be transcoded.
- Ambiguous or unsafe cases should be sent to manual review.

## 4K behaviour

- 4K defaults are conservative.
- Preserve the original video stream.
- Preserve audio quality where possible, especially surround and Atmos-capable formats.
- Strip non-English audio tracks when policy requires it.
- Strip non-English subtitle tracks when policy requires it.
- Do not transcode 4K by default.
- Low-confidence 4K cases should fall back to manual review rather than guesswork.

## Audio retention rules

- Keep English audio by default.
- Preserve the best surround track available.
- Preserve Atmos-capable audio where possible.
- Drop commentary tracks unless a profile explicitly keeps them.
- Avoid retaining redundant lower-value English tracks once the preferred set is preserved.

## Subtitle retention rules

- Keep English subtitles by default.
- Always preserve forced English subtitles.
- Remove non-English subtitles unless a profile overrides that rule.
- Keep hearing-impaired English subtitles if policy enables them.

## Output and replacement

- Output container defaults to MKV.
- Processed files return to the original folder by default.
- Replacement must be verification-gated.
- Deletion of the source should remain conservative until verification is trusted.

## Planned evolution

- per-library profiles
- manual review flags for ambiguous cases
- protected-file rules
- richer explainability for why a stream was kept or removed
