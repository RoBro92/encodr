# Media Policy

## Intent

Policy is YAML-driven, explicit, and deterministic. The same file under the same policy version and profile context should always produce the same planning result.

## Non-4K behaviour

- non-4K files may be skipped, remuxed, transcoded, or sent to manual review
- `skip` is used only when the file already appears compliant
- `remux` is used when container or stream clean-up is sufficient
- `transcode` is used when codec/video policy requires it
- ambiguous or low-confidence cases fall back to manual review

## 4K behaviour

- 4K defaults are conservative
- preserve original video
- preserve remaining selected English audio
- preserve selected English subtitles
- strip non-English audio/subtitles where policy says so
- do not transcode 4K under the default strip-only mode
- if 4K expectations cannot be satisfied confidently, require manual review

## Audio rules

- keep preferred-language audio, currently English by default
- preserve the best surround-capable English track where possible
- preserve Atmos-capable English audio where visible
- preserve 7.1 over 5.1 where practical
- remove commentary-ish tracks by default unless policy says otherwise
- if no acceptable English audio exists, route to manual review

## Subtitle rules

- keep forced English subtitles
- keep one main English subtitle when policy says so
- keep English hearing-impaired subtitles only when policy says so
- remove non-English subtitles by default
- ambiguous forced-subtitle cases can trigger warnings or manual review

## Output and replacement

- MKV is the default output container
- output is staged to scratch first
- ffmpeg success is not final success
- final success requires verification plus successful placement back into the source directory
- original deletion remains conservative and policy-driven

## Manual review and protection

- files with missing acceptable English audio, ambiguous subtitle metadata, low confidence, or planner protection flags enter manual review
- 4K/HDR/DV-like/Atmos-capable or preserve-oriented files can be marked protected
- protected/manual-review items require explicit operator action before processing continues

## Current limitation

The policy model includes rename templates, but advanced rich rename generation is still limited. Current placement remains conservative and source-name oriented unless later milestones extend naming further.
