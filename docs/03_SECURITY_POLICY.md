# 03. Security and Policy

## File Security

Project files are generated only under the configured project root.

Forbidden:

- Absolute path resources.
- `../` path traversal.
- External URL resources.
- External `.kdenlive` inputs.
- Text insertion into XML without escaping.

Allowed media extensions:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`

Kdenlive policy:

- Use only self-generated templates.
- Open only self-generated outputs as editable targets.
- Record template and Kdenlive version metadata before production use.

## LLM Security

Forbidden:

- Storing API keys in DB, logs, or repo files.
- Sending full source posts to an LLM.
- Sending full comments to an LLM.
- Including inferred personal information in LLM input.
- Storing validation-failed LLM output as an artifact.

Allowed:

- User-written summary.
- Minimal source metadata.
- Risk flags.
- Timeline fact basis.
- D manifest notes.

## Content Safety

Forbidden:

- Identity inference.
- Nickname inference or exposure.
- Personal-info inference.
- Legal accusation.
- Unsupported facts, counts, or rankings.
- Direct quotation of full source text or comments.
- Encouraging source capture reuse.
- Amplifying targeted harassment.
- Amplifying hate.

## D Image Manifest Safety

The D manifest is a human confirmation gate before narration/title generation.

Forbidden for E readiness:

- Missing or unsafe image files.
- Absolute paths, `../`, or external image URLs.
- Unconfirmed rights.
- Personal information in images.
- Original source post or comment screenshots/captures.
- Community logos without a later explicit allowlist.
- Faces without rights or consent confirmation.
- Image hash mismatches.

The workflow must not extract or store EXIF metadata, GPS/location data, OCR
text, facial recognition data, raw source text, raw comments, or screenshots.

## E Script and Title Safety

E generation runs only after the D readiness gate accepts the local image
manifest.

Forbidden in E output:

- Direct source or comment quotation.
- Real-name, nickname, or personal-information inference.
- Crime assertions or hard factual overclaims.
- Fabricated numbers, counts, rankings, or percentages.
- Original screenshot/capture reliance.
- Raw-source, API-secret, absolute-path, EXIF/GPS, OCR, or facial-recognition
  references.

E providers are injected test/mock boundaries in the local skeleton. No real LLM
API client, network call, scraping, TTS, rendering, or uploading belongs in this
phase.

## F Kdenlive Skeleton Safety

F generation is a local editing handoff only. It must generate MLT/Kdenlive XML
from validated local `timeline.json`, `d_image_manifest.json`, and
`e_script.json` artifacts.

Forbidden:

- Parsing, copying, trusting, or mutating external `.kdenlive` files.
- Absolute paths, `../` traversal, or external URLs in XML resources.
- Raw source posts, comments, raw HTML, screenshots, API keys, secrets, tokens,
  passwords, EXIF/GPS metadata, OCR output, or facial-recognition metadata in
  XML or F artifacts.
- Running Kdenlive or melt.
- Rendering, uploading, TTS, voice synthesis, BGM generation, or provider calls.

F output must keep project status at `script_generated` and must not imply that
final editing, recording, rendering, or upload has happened.

## Dev Smoke CLI Safety

The dev smoke CLI must require the explicit `--use-fake-providers` flag. It must
not create or select real providers, read API keys, make network calls, scrape,
download images, render, upload, run TTS, or mutate production Kdenlive XML.

## Dev Inspect CLI Safety

The dev inspect CLI is read-only. It must open an existing DB in read-only mode,
must not create or modify DB rows, must not write files, and must not call the
smoke pipeline or provider code. Stored artifact paths are untrusted input and
must be validated before any file existence or SHA-256 check.

## CI Safety

GitHub Actions CI must use only dev dependencies, not the optional LLM provider
extras. CI may install Python dependencies from package indexes, but must not
require API keys, call real providers, scrape, render, upload, or mutate
production Kdenlive XML.

## Collection Safety

Default configuration:

```toml
[collectors.dcinside]
enabled = false
mode = "manual_url_only"
requires_terms_review = true
store_raw_body = false
store_comments = false
```

Forbidden:

- Automated crawling by default.
- Login bypass.
- CAPTCHA bypass.
- Bot detection bypass.
- IP rotation.
- Header spoofing.
- Rate-limit bypass.
- Collection without terms or robots review.

## Logging

Logs must not include:

- API keys.
- Secrets.
- Full source text.
- Full comments.
- Personal information.
- Original captured source screenshots.

Logs should contain redacted summaries and error codes.
