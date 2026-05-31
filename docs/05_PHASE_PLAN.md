# 05. Phase Plan

## Phase 0. Repo Baseline

Goals:

- Fix docs and data contracts into the repo.
- Create Python package scaffold.
- Create test execution environment.

Done when:

- `pytest` runs.
- Docs exist.
- Pydantic models import.
- SQLite schema init smoke test passes.

## Phase 1. Local Project Core

Goals:

- SQLite initialization.
- Project directory generator.
- Manual candidate to project creation.
- State transitions.

Done when:

- One manual candidate fixture creates a project row and folder.
- `source.json` is created.
- Illegal state transitions are rejected.
- Project IDs are generated from runtime KST dates and same-day sequences.
- Ordinary create failures roll back the project row and generated folder.

## Phase 2. B Generation Skeleton

Goals:

- B Pydantic model.
- Mock LLM client.
- Validation and retry structure.

Done when:

- Valid fixture passes.
- Nonconsecutive scene IDs, duration errors, and missing source basis fail.
- Mock provider retry succeeds when a later response validates.
- Retry exhaustion leaves no B artifact, no plan row, and no status change.
- Success writes `b_scene_plan.json`, inserts DB records, and transitions status
  to `planned`.

## Phase 3. C Compiler Prototype

Goals:

- `timeline.json` generation.
- Start-time assignment.
- Placeholder PNG generation.
- Text overlay PNG generation.
- Kdenlive XML/path validation skeleton.

Done when:

- Timeline validation passes.
- Slot files exist.
- Overlay files exist.
- Path traversal and external URL resources are rejected.
- `notes/replace_images.md` is generated with safety and rights reminders.
- Success inserts timeline/artifact records and transitions status to
  `project_generated`.
- Wrong status or missing/invalid B artifacts leave no C timeline/artifact/status
  side effects.

## Phase 4. D Image Manifest

Goals:

- Record per-slot image notes and rights confirmation.
- Validate D manifest.

Done when:

- Every slot has a status.
- Replaced slots have `actual_image_note`.
- Missing rights confirmation blocks E.
- Draft initialization writes `d_image_manifest.json` and transitions to
  `waiting_for_user_images`.
- Confirmation verifies local PNG files, rights metadata, and hashes before
  transitioning to `images_inserted`.
- E readiness helper rejects unsafe manifests without generating E output.

## Phase 5. E Script and Title Skeleton

Goals:

- E Pydantic model.
- Mock LLM client.
- Title and narration validation.

Done when:

- Every timeline scene has narration.
- Recommended title is one of the candidates.
- Unsupported claims are rejected.
- D readiness is required before generation.
- Retry exhaustion leaves no E artifact, script row, or status transition.
- Success writes `e_script.json`, inserts script/artifact/LLM-run records, and
  transitions to `script_generated`.

## Phase 6. Integration and Smoke Tests

Goals:

- Manual source -> B -> C -> D -> E happy path.
- Status history and artifact/DB verification for the local backend path.
- Dev-only CLI wrapper for the deterministic local smoke path.
- Phase 6/F self-generated Kdenlive/MLT skeleton handoff from timeline, D
  manifest, and E script.
- Kdenlive manual-open smoke test in a later production-project phase.

Done when:

- Generated projects have no missing media.
- Vertical 1080x1920 30fps metadata is verified.
- The deterministic local smoke run reaches `script_generated`.
- The dev smoke CLI requires explicit fake providers and can print JSON or a
  concise human-readable summary.
- The read-only dev inspect CLI can report project status events, artifact rows,
  file existence, hash matches, and strict artifact problems without mutation.
- The read-only dev project verifier can validate an existing A to E or A to F
  project folder, JSON contracts, local PNG assets, DB artifact rows, hashes,
  and F XML without mutation.
- The dev Kdenlive CLI can generate Phase 6/F local editing handoff artifacts
  for an existing `script_generated` project with explicit
  `--confirm-local-write`.
- The dev smoke runner and CLI can optionally run F with explicit `run_f=True`
  or `--run-f`, while the default smoke path remains A to E.
- The protected-main baseline audit documents the current modules, contracts,
  DB tables, state transitions, CLI surface, CI, security boundaries, and gaps.
- F generation writes `project.kdenlive`, `f_kdenlive_manifest.json`, and
  `notes/manual_kdenlive_editing.md` without rendering, TTS, upload, provider
  calls, or external `.kdenlive` trust, and keeps status at `script_generated`.
- Status events include A/B/C/D/E transitions.
- DB rows and SHA-256 artifact records are verified end to end.
- Broader multi-sample and Kdenlive manual-open smoke tests remain future work.
