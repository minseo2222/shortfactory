# 02. Data Contracts

Every artifact has an explicit schema version and must pass Pydantic validation
before storage.

## CandidateCard

Ephemeral candidate cards exist in session memory only.

```python
EphemeralCandidate.status = "new" | "selected" | "rejected_in_session"
```

Required fields:

- `candidate_id`
- `title`
- `source_url`
- `community`
- `collected_at`
- `summary`
- `hook`
- `why_shortable`
- `risk_flags_for_user`
- `status`

## Project.status

Persisted project statuses:

```text
candidate_selected
planned
project_generated
waiting_for_user_images
images_inserted
script_generated
recording_done
final_editing
completed
archived
failed
```

Transitions are centralized in `src/shorts_pipeline/state_machine.py`.

## ProjectStatusEvent

Status history is append-only in `project_status_events`.

Fields:

- `project_id`
- `from_status`
- `to_status`
- `stage`
- `reason`
- `created_at`

The local smoke path records:

```text
candidate_selected -> planned -> project_generated
-> waiting_for_user_images -> images_inserted -> script_generated
```

## SourceArtifact

Schema version: `source.v2.1`

Created when a user selects one manual candidate and starts a project. It stores
only minimal source metadata:

- `project_id`
- `source_url`
- `source_community`
- `source_title`
- `user_or_llm_summary`
- `hook`
- `why_shortable`
- `risk_flags_for_user`
- `created_at`
- `storage_policy`

`storage_policy.full_source_post_stored`,
`storage_policy.full_comments_stored`, and
`storage_policy.original_screenshot_stored` must all be `false`.

## BScenePlan

Schema version: `b_scene_plan.v2.1`

Fields:

- `selected_style`
- `style_reason`
- `target_duration_sec`
- `scene_plan`
- `risk_flags`

`ScenePlanItem` fields:

- `scene_id`: `s01`, `s02`, ...
- `duration_sec`: greater than 1 second and no more than 12 seconds.
- `purpose`: one of `hook`, `context`, `turn`, `reaction`, `contrast`,
  `payoff`, `cta`
- `screen_text`: max 40 characters.
- `visual_direction`: max 300 characters.
- `image_slot_description`: max 300 characters.
- `narration_intent`: max 300 characters.
- `source_basis`: 1 to 5 short basis labels.
- `do_not_say`

Validation rules:

- Scene IDs must be consecutive.
- Total duration must be within 5 seconds of `target_duration_sec`.
- `source_basis` must be non-empty.
- `screen_text` must not look copied from stored source metadata.
- `do_not_say` must include at least one safety guard.
- B generation uses an injected provider protocol only; no real network provider
  is part of Phase 2.
- Successful B generation writes `b_scene_plan.json`, inserts `plans`,
  `artifacts`, and `llm_runs` records, and transitions project status from
  `candidate_selected` to `planned`.
- `artifacts.relative_path` stores a safe relative path such as
  `PRJ_YYYYMMDD_0001/b_scene_plan.json` plus a SHA-256 digest.

## TimelineJson

Schema version: `timeline.v2.1`

Rules:

- C computes `start_sec`.
- `project_id` must match the selected project.
- `canvas` is vertical 1080x1920 at 30fps and carries the B target duration.
- `source` contains only safe minimal metadata from `source.json`.
- Every scene has a user image path and text overlay path.
- Scene `fact_basis` comes from B `source_basis`.
- Scene `avoid_claims` comes from B `do_not_say`.
- Total duration is 30 to 60 seconds.
- Successful C compile writes `timeline.json`, placeholder PNGs, initial user
  image slot PNGs, text overlay PNGs, and `notes/replace_images.md`.
- Successful C compile inserts a `timelines` row, C artifact rows with safe
  relative paths and SHA-256 digests, and transitions status from `planned` to
  `project_generated`.

## DImageManifest

Schema version: `d_image_manifest.v2.1`

Required per slot:

- `slot_id`
- `scene_id`
- `status`: `placeholder` or `replaced`
- `planned_image_path`
- `actual_image_path`
- `actual_image_note`
- `source_type`
- `rights_confirmed_by_user`
- `contains_face`
- `face_rights_confirmed`
- `contains_personal_info`
- `contains_original_capture`
- `contains_community_logo`
- `image_sha256`

Rules:

- Draft initialization maps every timeline image slot into
  `d_image_manifest.json` and moves status from `project_generated` to
  `waiting_for_user_images`.
- Confirmation verifies slot order, safe relative paths, local PNG files,
  1080x1920 dimensions, SHA-256 hashes, image notes, and rights metadata.
- Ready manifests move status from `waiting_for_user_images` or
  `project_generated` to `images_inserted`.
- Future E generation must use the D readiness gate and must fail on unconfirmed
  rights, personal information, original captures, unsafe paths, missing files,
  community logos, face-rights gaps, or hash mismatches.

## EScript

Schema version: `e_script.v2.1`

Fields:

- `narration_script`: one narration line per timeline scene.
- `title_candidates`: 5 to 12 candidate titles.
- `recommended_title`: one exact title from `title_candidates`.
- `forbidden_claims`: safety guards for identity, privacy, crime-claim,
  fabricated-number, direct-quote, and original-capture risks.

Validation rules:

- `recommended_title` must be one of `title_candidates`.
- Narration scene IDs must match `timeline.json` exactly and in order.
- Narration must be speakable for scene duration and tied to scene fact basis,
  avoid-claims, or D image notes.
- Titles must not introduce unsupported numbers, hard factual overclaims, real
  names, or nicknames.
- Narration and titles must not look like direct copies from stored source
  metadata.
- E generation requires `images_inserted` status and the D readiness gate.
- Successful E generation writes `e_script.json`, inserts `scripts`,
  `artifacts`, and `llm_runs` records, and transitions status to
  `script_generated`.

## FKdenliveManifest

Schema version: `f_kdenlive_project.v2.1`

Generated by Phase 6/F from a project in `script_generated` status. The F
output is a local editing handoff only:

- `project.kdenlive`
- `f_kdenlive_manifest.json`
- `notes/manual_kdenlive_editing.md`

Fields:

- `project_id`
- `kdenlive_project_path`
- `canvas_width`: fixed at `1080`
- `canvas_height`: fixed at `1920`
- `fps`: fixed at `30`
- `total_duration_sec`
- `total_frames`
- `scenes`
- `source_artifacts`
- `generated_at`
- `generated_by`
- `external_template_used`: always `false`
- `rendering_performed`: always `false`
- `warnings`

Rules:

- F generation requires `script_generated` status and keeps project status
  unchanged.
- Inputs are loaded from `source.json`, `timeline.json`,
  `d_image_manifest.json`, and `e_script.json`.
- D readiness validation is reused before XML generation.
- One scene reference is emitted for each timeline scene.
- Image resources must match D `actual_image_path` values.
- Text overlay resources must match timeline `text_overlay_path` values.
- All paths are safe relative paths under the project.
- The generated XML is self-generated code output. External `.kdenlive` files
  are not parsed, copied, trusted, or mutated.
- F does not render, upload, generate TTS, call providers, or run Kdenlive/melt.
- Successful F generation inserts or updates artifact rows for
  `kdenlive_project`, `f_kdenlive_manifest`, and
  `manual_kdenlive_editing_guide`.

## SQLite Tables

Required first-run tables:

- `projects`
- `llm_runs`
- `plans`
- `timelines`
- `artifacts`
- `image_manifests`
- `scripts`
- `project_status_events`
- `events`

DB rules:

- `PRAGMA foreign_keys=ON`
- `PRAGMA journal_mode=WAL`
- Artifact paths are relative paths under the project root.
- Do not store full source text, full comments, API keys, or secrets.

## SmokeRunResult

Schema version: `smoke_run.v2.1`

Returned by the local integration smoke runner. It is not written as a project
artifact.

Fields:

- `project_id`
- `final_status`
- `status_sequence`
- `artifact_checks`
- `db_table_counts`

## ProjectInspectionResult

Schema version: `project_inspection.v2.1`

Returned by the read-only dev inspect command. It is not written as a project
artifact and must not trigger DB initialization or migrations.

Fields:

- `project`
- `status_sequence`
- `status_events`
- `artifacts`
- `artifact_problem_count`
- `warnings`

Each artifact inspection row includes the stored artifact type, relative path,
optional SHA-256, path safety result, optional file existence result, optional
hash-match result, and any verification error. Unsafe stored paths are reported
without reading the referenced file.
