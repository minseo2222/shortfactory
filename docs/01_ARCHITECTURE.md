# 01. Architecture

```text
[Streamlit UI]
  -> A. Manual candidate board
  -> B. Scene plan generator
  -> C. Project compiler
  -> D. Human image insertion
  -> E. Narration/title generator
  -> SQLite + local project folder
```

## A. Candidate Input

The default v2.1 mode is `manual_url_only`.

The user manually enters:

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
- `project.kdenlive`
- `notes/replace_images.md`

Rules:

- LLM output does not define `start_sec`.
- C computes `start_sec` by accumulating scene durations.
- Initial `slot_XXX.png` files may be placeholder copies.
- Text overlays are PNG files.

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
    assets/
      placeholders/
      user_images/
      text_overlays/
    notes/
    exports/
    logs/
```
