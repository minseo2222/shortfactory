# 01. Architecture

```text
[Streamlit UI]
  -> A. Manual candidate board
  -> B. Scene plan generator
  -> C. Project compiler
  -> D. Human image insertion
  -> E. Narration/title generator
  -> F. Self-generated Kdenlive skeleton
  -> SQLite + local project folder
```

## A. Candidate Input

The default mode is `manual_url_only`. v2.2 adds an opt-in
`assisted_discovery` mode implemented by `src/shorts_pipeline/sources/`:

- `RssSourceProvider` - published RSS/Atom feeds (Ruliweb `/rss`, Inven news,
  or any feed URL).
- `SingleLinkFetchProvider` - one user-pasted public URL, fetched once after a
  robots.txt check, with no bypass of login/CAPTCHA/Cloudflare walls.
- `YouTubeSourceProvider` - official YouTube Data API (`chart=mostPopular`,
  `regionCode=KR`), key from env.
- `NaverSearchSourceProvider` / `NaverDataLabProvider` - official Naver
  search and search-trend APIs, Client ID/Secret from env.

Each returns bounded `DiscoveredCandidate` metadata (title, URL, score, source,
short excerpt); network egress happens only on user trigger and only via these
lawful paths. The UI then drafts an editable candidate from the chosen item.

The user manually enters (or assisted discovery pre-fills):

- `source_url`
- `community`
- `source_title`
- `summary`
- `hook`
- `why_shortable`
- `risk_flags_for_user`

Candidate cards are session-ephemeral. Only a selected candidate starts a
project and gets persisted as minimal metadata.

## B. Scene Plan Generation

Input:

- Selected source metadata.
- User-written summary.
- Hook.
- Risk flags.

Output:

- `b_scene_plan.json`

Rules:

- No direct full-source quotation.
- No full comment quotation.
- No identity, nickname, or personal-info inference.
- No unsupported legal claims.
- No facts, counts, or rankings without a source basis.
- Store only after Pydantic validation.

## C. Project Compiler

C is a compiler, not a renderer.

Input:

- `source.json`
- `b_scene_plan.json`

Output:

- `timeline.json`
- `assets/placeholders/slot_XXX_placeholder.png`
- `assets/user_images/slot_XXX.png`
- `assets/text_overlays/sXX_text.png`
- `notes/replace_images.md`

Rules:

- LLM output does not define `start_sec`.
- C computes `start_sec` by accumulating scene durations.
- Initial `slot_XXX.png` files may be placeholder copies.
- Text overlays are PNG files.
- C does not generate `project.kdenlive`; that is produced later by F.

## D. Image Insertion

The user inserts images by either:

- Replacing `assets/user_images/slot_001.png` with the same filename.
- Replacing slot clips directly in Kdenlive.

D completion requires `d_image_manifest.json` with:

- `image_insert_completed`
- `user_confirmed`
- `actual_image_note`
- `rights_confirmed_by_user`
- `contains_face`
- `contains_personal_info`
- `contains_original_capture`

## E. Narration and Titles

Input:

- `timeline.json`
- `d_image_manifest.json`
- Source reference metadata.

Output:

- `e_script.json`

Rules:

- User records narration manually.
- No automated TTS.
- Narration must be speakable.
- Titles must not invent facts.
- Recommended title must be one title candidate.

## F. Kdenlive Skeleton

F is a self-generating compiler, not a renderer.

Input:

- `source.json`
- `timeline.json`
- `d_image_manifest.json`
- `e_script.json`

Output:

- `project.kdenlive`
- `f_kdenlive_manifest.json`
- `notes/manual_kdenlive_editing.md`

Rules:

- F requires `script_generated` status and keeps the project status unchanged.
- The XML is self-generated from validated C/D/E artifacts only.
- External `.kdenlive` files are never parsed, copied, trusted, or mutated.
- F does not render, upload, generate TTS, call providers, or run Kdenlive/melt.
- All resource paths are safe relative paths under the project.

## Local Smoke Path

The backend services have a deterministic local A -> B -> C -> D -> E smoke
runner for integration tests. It uses manually constructed fixture data and
caller-injected fake providers only; it does not call external APIs, download
images, render media, or mutate production Kdenlive XML.

## Storage Layout

```text
projects/
  PRJ_YYYYMMDD_NNNN/
    source.json
    b_scene_plan.json
    timeline.json
    d_image_manifest.json
    e_script.json
    project.kdenlive
    f_kdenlive_manifest.json
    assets/
      placeholders/
      user_images/
      text_overlays/
    notes/
      replace_images.md
      manual_kdenlive_editing.md
    exports/
    logs/
```
