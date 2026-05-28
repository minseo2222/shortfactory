# 00. Project Brief

Shorts Pipeline v2.1 is a local MVP for producing short-form videos from
manually selected community-source ideas.

The user enters a source URL, title, summary, hook, shortability rationale, and
risk flags. Only selected sources become projects. LLM-shaped outputs must be
structured and validated before they are stored as artifacts.

## Target User Flow

1. A: User manually creates a candidate card.
2. A: User selects one candidate and starts a project.
3. B: A structured `b_scene_plan.json` is generated and validated.
4. C: The compiler generates `timeline.json`, media slots, overlay PNGs, and a
   local Kdenlive project file.
5. D: User manually inserts or replaces images and records `d_image_manifest.json`.
6. E: Narration text and title candidates are generated from the timeline and
   image manifest.
7. User records narration and completes the final edit manually.

## MVP Success Criteria

1. One manual source fixture can create a project row and project folder.
2. B output passes Pydantic and content-safety validation.
3. C output produces a schema-valid `timeline.json`.
4. Placeholder and overlay media files exist.
5. Generated `.kdenlive` files parse as XML and pass path validation.
6. D manifest validation blocks unsafe E input.
7. E output includes narration for every scene and a recommended title from the
   title candidate list.

## Explicit Non-Goals

- Automated community crawling.
- Storing full source text or full comments.
- Automated TTS.
- Automated upload.
- Automated image insertion.
- Processing external `.kdenlive` files.
- Kdenlive title-clip generation.
- Automated commercial/legal review.

## First Run Goals

- Repository scaffold.
- Documentation.
- SQLite schema.
- Pydantic models.
- State machine.
- Safe path/XML helpers.
- Test skeleton.

Streamlit UI, real LLM API calls, and production Kdenlive XML mutation are
intentionally deferred.
