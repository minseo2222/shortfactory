# Baseline Repository Audit

## Audit Metadata

- Audit date: 2026-05-29 KST
- Task ID: `CODEX_PROMPT_014`
- Base branch: `origin/main`
- Base SHA: `4c0500ca856b888da1ad1b93b28f7c5f7a6984ec`
- Working branch: `codex/014-baseline-audit`
- Branch protection verification: succeeded with `gh api`
- Local tests: passed with `python -m pytest` (`117 passed`)
- Ruff: passed with `python -m ruff check .`
- Scope: documentation and repository-governance verification only
- Text hygiene: LF line endings and no hidden/bidirectional controls in selected text files

## Repository Governance

- `main` is protected, verified through GitHub API.
- Required status check: `pytest and ruff`.
- Strict status checks are enabled.
- Admin enforcement is enabled.
- Force pushes and branch deletions are disabled.
- Pull request review settings exist with `required_approving_review_count = 0`.
- Future Codex tasks must start from latest `origin/main`, create a task branch named
  `codex/<task-id>-short-title`, run local checks, push the branch, and report a compare
  URL or PR URL.
- Direct commits to `main` are not allowed after the initial repository setup.
- GPT Pro reviews branch diffs before merge.

Verified branch protection summary:

```text
main protected: true
required_status_checks.strict: true
required_status_checks.contexts: ["pytest and ruff"]
enforce_admins.enabled: true
required_pull_request_reviews.required_approving_review_count: 0
allow_force_pushes.enabled: false
allow_deletions.enabled: false
restrictions: null
```

## Current File Inventory

### Root

- `.env.example` - empty local environment template; no committed real secrets.
- `.gitattributes` - enforces LF line endings for repository text files.
- `.gitignore` - excludes Python caches, virtualenvs, local DBs, local projects, exports, media,
  and secret files.
- `AGENTS.md` - Codex operating rules, hard boundaries, and GitHub branch workflow.
- `README.md` - project overview, safety rules, dev CLI usage, CI, and GitHub workflow.
- `gpt_pro_first_response_a_to_f.md` - historical GPT Pro review/prompt context.
- `pyproject.toml` - package metadata, runtime dependencies, optional extras, console script,
  pytest configuration, and Ruff configuration.
- `requirements.lock.txt` - version pins of the verified core + dev dependency closure;
  optional `ui`/`llm` extras are intentionally unpinned.

### GitHub Workflow

- `.github/workflows/ci.yml` - CI on `main`, `codex/**`, and PRs to `main`.

### Docs

- `docs/00_PROJECT_BRIEF.md` - product brief, user flow, MVP criteria, and non-goals.
- `docs/01_ARCHITECTURE.md` - A through E architecture and local storage layout.
- `docs/02_DATA_CONTRACTS.md` - artifact, status, Pydantic, and SQLite contract summary.
- `docs/03_SECURITY_POLICY.md` - file, LLM, content, D, E, CLI, CI, collection, and logging safety.
- `docs/04_CODEX_WORKFLOW.md` - GPT Pro and Codex workflow rules.
- `docs/05_PHASE_PLAN.md` - phase-by-phase implementation plan through integration smoke.
- `docs/06_TEST_PLAN.md` - unit, DB, timeline, D, security, integration, manual, and red-team test plan.
- `docs/07_BASELINE_AUDIT.md` - this protected-main baseline audit.

### Schemas and Templates

- `schemas/README.md` - policy that JSON schemas are generated from Pydantic models.
- `templates/TEMPLATE_METADATA.json` - metadata for the dev-only Kdenlive template stub.
- `templates/kdenlive_vertical_1080x1920_30fps.kdenlive` - self-generated dev-only XML stub,
  not a production template and not external input.

### Source

- `src/shorts_pipeline/__init__.py` - package marker and version.
- `src/shorts_pipeline/config.py` - KST time helper and environment-backed settings.
- `src/shorts_pipeline/models.py` - strict Pydantic contracts for candidates, source, B, C, D,
  E, smoke results, status events, and inspection results.
- `src/shorts_pipeline/db.py` - SQLite connections, schema initialization, read-only DB connection,
  status event insertion, and status event listing.
- `src/shorts_pipeline/security.py` - safe relative path checks, root containment checks,
  external resource rejection, XML escaping, media extension validation, and SHA-256 hashing.
- `src/shorts_pipeline/state_machine.py` - project statuses and allowed transitions.
- `src/shorts_pipeline/project_service.py` - Phase A manual candidate selection to project row,
  folder tree, and `source.json`.
- `src/shorts_pipeline/b_service.py` - Phase B provider-injected scene plan generation,
  validation, retry, persistence, and status transition.
- `src/shorts_pipeline/c_service.py` - Phase C timeline compiler, image slots, overlays,
  replacement guide, artifact persistence, and status transition.
- `src/shorts_pipeline/d_service.py` - Phase D draft manifest, confirmation, image validation,
  rights gate, hashes, persistence, and E readiness helper.
- `src/shorts_pipeline/e_service.py` - Phase E provider-injected script/title generation,
  safe context construction, validation, retry, persistence, and status transition.
- `src/shorts_pipeline/f_service.py` - Phase F self-generated Kdenlive/MLT skeleton generation,
  manifest/XML validation, manual guide writing, artifact persistence, and rollback.
- `src/shorts_pipeline/smoke.py` - deterministic local A to E integration smoke runner
  with optional F handoff verification.
- `src/shorts_pipeline/dev_cli.py` - dev-only `smoke`, read-only `inspect`, and
  local-write `generate-kdenlive` CLI commands.
- `src/shorts_pipeline/dev_fakes.py` - deterministic fake B and E providers for local smoke runs.
- `src/shorts_pipeline/inspect.py` - read-only project inspection API.
- `src/shorts_pipeline/llm/__init__.py` - LLM helper package marker.
- `src/shorts_pipeline/llm/b_provider.py` - B provider protocol only.
- `src/shorts_pipeline/llm/e_provider.py` - E provider protocol only.
- `src/shorts_pipeline/llm/validators.py` - LLM-shaped artifact validation helpers and D readiness helper.
- `src/shorts_pipeline/llm/real_providers.py` - optional, opt-in real LLM adapters
  (OpenAI/Anthropic/Gemini) loaded dynamically via importlib; disabled by default and never
  called by tests, CI, or the default pipeline path.
- `src/shorts_pipeline/projectgen/__init__.py` - project generation helper package marker.
- `src/shorts_pipeline/projectgen/timeline.py` - timeline start-time assignment and B-to-timeline build helper.
- `src/shorts_pipeline/projectgen/placeholder.py` - local Pillow placeholder PNG generation.
- `src/shorts_pipeline/projectgen/text_overlay.py` - local transparent text overlay PNG generation.
- `src/shorts_pipeline/projectgen/replace_images.py` - local replacement instruction Markdown generation.
- `src/shorts_pipeline/projectgen/kdenlive.py` - standard-library XML builder for the
  self-generated F Kdenlive/MLT skeleton.
- `src/shorts_pipeline/ui/__init__.py` - local UI package marker.
- `src/shorts_pipeline/ui/controller.py` - Streamlit-free orchestration layer composing the
  A->F phase services, provider selection (default fake, opt-in real), and read helpers.
- `src/shorts_pipeline/ui/app.py` - thin Streamlit entry point rendering the local A->F flow;
  calls only the controller and performs no network egress.

### Tests

- `tests/fixtures/sample_source.json` - valid manual candidate fixture.
- `tests/fixtures/sample_b_scene_plan.json` - valid B scene plan fixture.
- `tests/test_models.py` - core model validation coverage.
- `tests/test_project_creation.py` - Phase A project creation, source artifact, path safety,
  ID sequence, and rollback coverage.
- `tests/test_b_generation.py` - Phase B provider injection, validation, retry, persistence,
  status transition, and no-provider behavior.
- `tests/test_c_compiler.py` - Phase C timeline, generated PNGs, replacement guide,
  DB artifacts, validators, and blocked input/status cases.
- `tests/test_d_image_manifest.py` - Phase D draft, confirmation, file/hash validation,
  rights and safety blockers, and E readiness gate.
- `tests/test_e_script_generation.py` - Phase E D-readiness requirement, provider injection,
  retry, validators, persistence, status transition, and rollback.
- `tests/test_f_kdenlive_project.py` - Phase F Kdenlive skeleton generation, XML/manifest
  validation, artifact hashes, safety blockers, status preservation, and rollback.
- `tests/test_redteam_content_safety.py` - red-team coverage for the docs/06 attack
  categories: real-name/nickname inference, crime assertion, fabricated numbers, direct
  source/comment quotation, original-capture reuse, and mockery of individuals.
- `tests/test_integration_smoke.py` - deterministic A to E smoke path, artifacts, DB rows,
  status history, and negative smoke behavior.
- `tests/test_multisample_smoke.py` - twelve distinct varied-scene-plan samples through the
  full A->F path, verifying status, scene-count match, Kdenlive profile, and no missing media.
- `tests/test_dev_cli.py` - dev smoke CLI JSON/human output, fake-provider gate, fixed clock,
  required args, directory creation, and clean stdout.
- `tests/test_dev_inspect_cli.py` - read-only inspect CLI, mutation checks, missing DB/root,
  artifact problems, hash mismatch, unsafe paths, strict mode, and verification skip flags.
- `tests/test_dev_cli_kdenlive.py` - dev Kdenlive CLI confirmation gate, JSON/human output,
  required args, unknown project, wrong status, and no-rendering flags.
- `tests/test_db.py` - SQLite initialization and status CHECK constraint coverage.
- `tests/test_security.py` - path traversal, absolute path, external URL, media extension,
  and XML escaping coverage.
- `tests/test_state_machine.py` - valid, invalid, and unknown state transition coverage.
- `tests/test_timeline.py` - start-time accumulation and scene order coverage.
- `tests/test_ci_workflow.py` - CI workflow trigger, dependency, action-version, pytest, Ruff,
  network/provider guard, and secret guard checks.
- `tests/test_real_llm_providers.py` - offline unit tests for the optional real LLM adapters:
  JSON parsing, prompt construction, opt-in resolver, SDK/key error paths, no-literal-import
  guard discipline, and service drop-in integration with a fake completion client.
- `tests/test_ui_controller.py` - Streamlit-free UI controller coverage: full A->F path,
  stage-by-stage status progression, provider selection, status events, and D payload builder.
- `tests/test_ui_app_smoke.py` - headless Streamlit `AppTest` smoke that drives `app.py` through
  the full A->F flow and asserts status progression and F handoff output; skipped when the `ui`
  extra is absent (offline CI).
- `tests/test_text_file_hygiene.py` - LF line-ending and hidden Unicode control checks for
  selected repo text files.

## Runtime Architecture Summary

The current local backend is a file-and-SQLite pipeline. A thin local Streamlit UI
(`src/shorts_pipeline/ui/`) drives the A->F flow through a Streamlit-free controller; it is
optional (the `ui` extra) and performs no network egress.

```text
manual candidate
-> project creation
-> B scene plan
-> C timeline/assets
-> D image manifest
-> E script/title
-> F Kdenlive handoff
-> smoke runner
-> dev CLI / inspect CLI / Kdenlive CLI
```

The runtime services are intentionally small and phase-scoped:

- A persists one selected manual candidate and writes `source.json`.
- B accepts an injected provider and writes validated `b_scene_plan.json`.
- C compiles deterministic timeline data and local PNG assets.
- D creates and confirms the image manifest and blocks unsafe E input.
- E accepts an injected provider and writes validated narration/title output.
- F generates local Kdenlive/MLT skeleton handoff files from validated C/D/E
  artifacts without rendering or external `.kdenlive` trust.
- Smoke composes the local A to E path with deterministic fake providers, and can
  explicitly opt into F handoff generation and verification.
- Inspect reads existing DB rows and artifact files without mutation.

## Data Contracts Summary

- `CandidateCard` - ephemeral manual candidate input with URL, title, community, summary,
  hook, shortability rationale, risk flags, and session-only status.
- `SourceArtifact` - `source.v2.1`; persisted minimal source metadata plus storage policy
  flags that must all remain false for full source post, comments, and original screenshot storage.
- `Project` - created project return model with `candidate_selected` status and local paths.
- `BScenePlan` and `ScenePlanItem` - `b_scene_plan.v2.1`; scene IDs, durations, purpose,
  screen text, visual directions, image-slot description, narration intent, source basis,
  and safety `do_not_say` guards.
- `TimelineJson`, `TimelineScene`, and `CanvasSpec` - `timeline.v2.1`; vertical canvas,
  safe source subset, computed start times, slot IDs, image paths, overlay paths, fact basis,
  and avoid claims.
- `DImageManifest` and `DImageSlotManifest` - `d_image_manifest.v2.1`; per-slot actual image
  paths, image notes, source type, rights confirmation, risk flags, and SHA-256.
- `EScript`, `NarrationLine`, and `TitleCandidate` - `e_script.v2.1`; one narration line per
  timeline scene, title candidates, recommended title, and forbidden claims.
- `FKdenliveManifest` and `FKdenliveSceneRef` - `f_kdenlive_project.v2.1`; local Kdenlive
  skeleton handoff metadata, deterministic frame references, D-confirmed image paths, timeline
  text overlay paths, source artifact references, and explicit no-template/no-render flags.
- `ProjectStatusEvent` - append-only status history item with from/to status, stage, reason,
  and timestamp.
- `SmokeRunResult` and `SmokeArtifactCheck` - local smoke verification result, not persisted
  as a project artifact.
- `ProjectInspectionResult`, `ProjectInspectionSummary`, and `ArtifactInspectionRow` -
  read-only inspection output, not persisted as a project artifact.

All Pydantic models use strict extra-field rejection through `StrictModel` or equivalent model
configuration.

## Database Schema Summary

`src/shorts_pipeline/db.py` creates and migrates the local SQLite schema. Connections enable
foreign keys and request WAL mode for write paths. Read-only inspection uses `mode=ro`.

- `projects` - one row per selected project; includes ID, project directory, source URL/title,
  community, status, created timestamp, updated timestamp, and path-safety CHECK constraints.
- `llm_runs` - provider-bound run metadata for B and E skeleton generations; stores stage,
  provider, model name, prompt version, schema version, status, optional error code, optional
  token counts, and timestamp.
- `plans` - one B plan row per project; stores schema version, serialized scene plan JSON,
  artifact path, optional LLM run ID, and timestamp.
- `timelines` - one C timeline row per project; stores schema version, serialized timeline JSON,
  total duration, artifact path, and timestamp.
- `artifacts` - artifact registry with project ID, artifact type, safe relative path, SHA-256,
  timestamp, and path-safety CHECK constraints.
- `image_manifests` - one D manifest row per project; stores schema version, serialized manifest
  JSON, artifact path, and timestamp.
- `scripts` - one E script row per project; stores schema version, optional LLM run ID,
  narration JSON, title candidates JSON, recommended title, artifact path, and timestamp.
- F outputs reuse `artifacts` rows for `kdenlive_project`, `f_kdenlive_manifest`, and
  `manual_kdenlive_editing_guide`; no F-specific table is added.
- `project_status_events` - append-only status transition history.
- `events` - generic event table retained for future event records.

## State Machine Summary

The centralized status set is:

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

The implemented A to E happy-path sequence is:

```text
candidate_selected
-> planned
-> project_generated
-> waiting_for_user_images
-> images_inserted
-> script_generated
```

Wrong-status service calls raise phase-specific `ProjectStatusError` exceptions and avoid
ordinary file/DB side effects. The state machine also allows failure transitions to `failed`,
post-script manual statuses (`recording_done`, `final_editing`, `completed`), and final
archival from `completed`.

## Pipeline Flow Summary

### A. Project Creation

- Input artifacts: one manually entered `CandidateCard`.
- Output artifacts: project folder tree and `source.json`.
- DB rows: `projects`, `project_status_events`.
- Status transition: no previous persisted status to `candidate_selected`.
- Validation gate: Pydantic candidate validation, generated project ID format, path containment,
  source artifact validation, and storage policy flags.
- Explicit non-goals: no scraping, no rejected candidate persistence, no full source/comment/raw
  HTML/screenshot storage.

### B. Scene Plan

- Input artifacts: `source.json` and project row in `candidate_selected`.
- Output artifacts: `b_scene_plan.json`.
- DB rows: `llm_runs`, `plans`, `artifacts`, `project_status_events`.
- Status transition: `candidate_selected -> planned`.
- Validation gate: injected provider only, Pydantic validation, scene ID sequence, duration window,
  source basis, `do_not_say` safety guard, direct-copy check, and forbidden raw-source terms.
- Explicit non-goals: no real OpenAI, Anthropic, Gemini, network, crawling, or provider adapter.

### C. Timeline and Assets

- Input artifacts: `source.json`, `b_scene_plan.json`, and project row in `planned`.
- Output artifacts: `timeline.json`, placeholder PNGs, user image slot PNGs, text overlay PNGs,
  `notes/replace_images.md`, BGM README, and exports README.
- DB rows: `timelines`, C `artifacts`, `project_status_events`.
- Status transition: `planned -> project_generated`.
- Validation gate: B/source validation, computed start times, total duration, slot sequence,
  safe source allowlist, safe relative paths, forbidden raw-source terms, and generated file hashes.
- Explicit non-goals: no production Kdenlive XML mutation, no rendering, no TTS, no upload,
  no automatic image download or insertion.

### D. Image Manifest

- Input artifacts: `timeline.json`, generated user image slot PNGs, and project row in
  `project_generated` or `waiting_for_user_images`.
- Output artifacts: `d_image_manifest.json`.
- DB rows: `image_manifests`, `artifacts`, `project_status_events`.
- Status transitions: `project_generated -> waiting_for_user_images` for draft initialization;
  `waiting_for_user_images -> images_inserted` or `project_generated -> images_inserted` for
  direct confirmation.
- Validation gate: slot order, safe relative paths, local PNG existence, 1080x1920 dimensions,
  SHA-256 matching, image notes, rights confirmation, face rights, no personal info, no original
  capture, no community logo, and forbidden raw-source terms.
- Explicit non-goals: no EXIF/GPS extraction, OCR, facial recognition, legal automation, image
  search, image download, or automatic insertion.

### E. Script and Titles

- Input artifacts: `source.json`, `timeline.json`, ready `d_image_manifest.json`, project row in
  `images_inserted`, and injected E provider.
- Output artifacts: `e_script.json`.
- DB rows: `llm_runs`, `scripts`, `artifacts`, `project_status_events`.
- Status transition: `images_inserted -> script_generated`.
- Validation gate: D readiness helper, safe E generation context, Pydantic validation, narration
  scene order, fact-basis connection, speakability heuristic, recommended-title membership,
  title uniqueness, numeric claim guard, hard overclaim guard, identity guard, mockery/hate
  guard, forbidden-claims categories, direct-copy check, raw-source term guard, absolute path
  guard, and metadata guard.
- Explicit non-goals: no real provider, no network, no TTS, no voice synthesis, no rendering,
  and no upload.

### F. Kdenlive Skeleton

- Input artifacts: `source.json`, `timeline.json`, ready `d_image_manifest.json`,
  `e_script.json`, and project row in `script_generated`.
- Output artifacts: `project.kdenlive`, `f_kdenlive_manifest.json`, and
  `notes/manual_kdenlive_editing.md`.
- DB rows: F `artifacts` rows only; no new F table and no status-event row.
- Status transition: none. Project status remains `script_generated`.
- Validation gate: source/timeline/D/E Pydantic validation, D readiness validation, E scene
  matching, manifest-to-input validation, deterministic frame calculations, safe relative
  resource paths, generated XML parse/profile/resource checks, local file existence checks,
  SHA-256 artifact records, and forbidden raw-source/API-secret term checks in XML.
- Explicit non-goals: no external `.kdenlive` parsing, no Kdenlive or melt execution, no
  rendering, no TTS or voice synthesis, no BGM generation, no upload, no provider calls,
  and no new status progression.

### Smoke Path

- Input artifacts: deterministic fictional manual fixture and injected fake B/E providers.
- Output artifacts: full local A to E artifact set in a temp or configured project root.
  With explicit F opt-in, also writes `project.kdenlive`, `f_kdenlive_manifest.json`,
  and `notes/manual_kdenlive_editing.md`.
- DB rows: project, B, C, D, E, artifact, LLM-run, and status-event records.
- Status transition: complete A to E sequence ending in `script_generated`; optional F
  does not add a status transition.
- Validation gate: reloads and validates JSON artifacts, checks generated files, verifies DB rows,
  validates status history, and verifies artifact hashes. Optional F also validates the F
  manifest, parses `project.kdenlive`, verifies F artifact rows, and confirms SHA-256 values.
- Explicit non-goals: no real providers, no external media, no rendering, no upload, no UI.

## CLI Surface Summary

### `python -m shorts_pipeline.dev_cli smoke`

- Purpose: run the deterministic local A to E smoke path.
- Required flags: `--db-path`, `--projects-root`, `--use-fake-providers`.
- Optional flags: `--fixed-clock`, `--run-f`, `--json`.
- Writes: local SQLite DB and local generated project files under the provided paths.
- Safety behavior: requires explicit fake-provider opt-in; `--run-f` additionally generates
  and verifies local F handoff files without rendering; does not read API keys; does not call
  real providers; does not scrape, download media, render, upload, TTS, or mutate production
  Kdenlive XML.

### `python -m shorts_pipeline.dev_cli inspect`

- Purpose: inspect an existing local project.
- Required flags: `--db-path`, `--projects-root`, `--project-id`.
- Optional flags: `--json`, `--no-verify-files`, `--no-verify-hashes`, `--strict`.
- Writes: nothing. It opens the DB in read-only mode and does not initialize or migrate.
- Safety behavior: validates stored artifact paths before file access; reports missing files,
  unsafe paths, and hash mismatches without repairing anything.

### `python -m shorts_pipeline.dev_cli generate-kdenlive`

- Purpose: generate Phase F local Kdenlive handoff artifacts for an existing
  `script_generated` project.
- Required flags: `--db-path`, `--projects-root`, `--project-id`, and
  `--confirm-local-write`.
- Optional flags: `--json`.
- Writes: `project.kdenlive`, `f_kdenlive_manifest.json`, and
  `notes/manual_kdenlive_editing.md` under the existing project folder.
- Safety behavior: uses the existing self-generated F service; does not render, run Kdenlive or
  melt, generate TTS/audio, upload, call providers, read API keys, or trust external
  `.kdenlive` files.

### `shorts-pipeline-dev`

- Purpose: console entry point for the same dev CLI.
- Entry point: `shorts_pipeline.dev_cli:main`.

## Test Coverage Summary

Current test suite on this branch includes the baseline tests plus audit-doc and text-hygiene
tests. The pre-audit `main` suite had 114 tests.

- `tests/test_models.py` - model and fixture validation, timeline creation, D readiness helper.
- `tests/test_project_creation.py` - A service happy path, ID sequence, source storage, rollback,
  and path safety.
- `tests/test_b_generation.py` - B happy path, retry success/exhaustion, validators, no-provider gate.
- `tests/test_c_compiler.py` - C happy path, timing, generated PNGs, guide, blocked status/input,
  and timeline validator.
- `tests/test_d_image_manifest.py` - D draft/confirmation, direct confirmation, readiness,
  unsafe flags, path, image, dimension, note, rights, face, hash, and forbidden field blockers.
- `tests/test_e_script_generation.py` - E happy path, D readiness requirement, provider gate,
  retry, validators, wrong status, forbidden fields, and rollback.
- `tests/test_f_kdenlive_project.py` - F happy path, D-confirmed image resources, timeline
  text overlay resources, deterministic frames, manual guide notes, blocked statuses,
  missing/invalid inputs, unsafe paths, forbidden XML terms, no external template use, and
  rollback.
- `tests/test_redteam_content_safety.py` - adversarial B/E payloads for each docs/06
  red-team category, asserting deterministic guard rejection without provider calls.
- `tests/test_integration_smoke.py` - full A to E smoke path, optional F smoke path,
  artifact checks, and negative smoke behavior.
- `tests/test_multisample_smoke.py` - multi-sample A->F coverage across varied scene plans,
  asserting status, Kdenlive profile, and media-resource existence.
- `tests/test_dev_cli.py` - smoke CLI behavior, including optional `--run-f`.
- `tests/test_dev_inspect_cli.py` - inspect CLI behavior and read-only guarantees.
- `tests/test_dev_cli_kdenlive.py` - Kdenlive CLI confirmation gate, JSON/human output,
  required args, unknown project, wrong status, and no-rendering flags.
- `tests/test_db.py` - schema and status constraint.
- `tests/test_security.py` - path and XML helpers.
- `tests/test_state_machine.py` - transition rules.
- `tests/test_timeline.py` - start-time helper.
- `tests/test_ci_workflow.py` - CI workflow contract.
- `tests/test_real_llm_providers.py` - optional real LLM adapter behavior, opt-in gating,
  error paths, and import-guard discipline, all without real SDKs or network.
- `tests/test_ui_controller.py` - UI orchestration controller: full A->F path, status
  progression, provider selection, and D payload construction without Streamlit.
- `tests/test_ui_app_smoke.py` - headless Streamlit AppTest smoke driving app.py through A->F;
  skipped offline, exercised locally with the `ui` extra installed.
- `tests/test_baseline_audit_doc.py` - baseline audit document structure and key claims.
- `tests/test_text_file_hygiene.py` - LF line-ending and hidden/bidirectional Unicode control
  checks for selected repository text files.

CI also runs `python -m ruff check .` and `python -m pytest`.

## Security Boundary Summary

- Real LLM provider adapters are opt-in and disabled by default; no real provider call is made
  by tests, CI, or the default pipeline path.
- Optional adapters load their SDK dynamically via importlib (no literal SDK import statements),
  read API keys only from the environment at client-construction time, and never store keys in
  artifacts, the DB, logs, or provider object attributes.
- B and E default to injected provider protocols and deterministic fake providers in tests/dev smoke.
- CI guards against direct imports of real provider/network clients in `src` and `tests`.
- No automated crawling or scraping is implemented.
- No full source post, full comment, raw HTML, source screenshot, API key, or secret storage is
  allowed in artifacts.
- Source artifacts store only minimal metadata and explicit storage policy flags.
- Generated artifact paths are safe relative paths and are checked against project-root containment.
- Artifact rows store SHA-256 hashes; smoke and inspect verify them.
- D image manifest blocks E readiness for unconfirmed rights, personal information, original
  captures, unsafe paths, missing files, dimension/format problems, face-rights gaps, community
  logos, and hash mismatches.
- No EXIF/GPS metadata extraction or storage exists.
- No OCR or facial recognition exists.
- No automatic image download, image search, or image insertion exists.
- No TTS, rendering, uploading, or YouTube behavior exists.
- No production Kdenlive XML mutation exists.
- External `.kdenlive` files are not trusted or parsed as inputs.
- F Kdenlive skeleton output is self-generated from validated local artifacts, uses safe
  relative local paths only, keeps status at `script_generated`, and does not run Kdenlive,
  melt, rendering, TTS, upload, providers, or network calls.
- The dev Kdenlive CLI requires explicit `--confirm-local-write` before invoking the F service.
- Dev inspect is read-only and does not call smoke, providers, or DB initialization.
- Text hygiene tests block CRLF/CR-only line endings and hidden/bidirectional Unicode controls
  in selected tracked text files.

## CI Summary

- Workflow file: `.github/workflows/ci.yml`.
- Triggers: push to `main`, push to `codex/**`, and pull request to `main`.
- Runner: Ubuntu GitHub-hosted runner.
- Python version: `3.11`.
- Dependency install: `python -m pip install -e ".[dev]"`.
- Lint: `python -m ruff check .`.
- Tests: `python -m pytest`.
- Network/provider import guard: scans Python imports in `src` and `tests`.
- Obvious-secret guard: scans `src`, `tests`, and `.github` for token/key patterns.
- Required branch-protection check name: `pytest and ruff`.
- CI does not install optional `llm` extras and does not require API keys.

## Known Risks and Gaps

- Real LLM provider adapters are opt-in and disabled by default; they have no real-SDK or
  network coverage in CI, so provider output quality is unverified.
- A local Streamlit UI drives A->F. The controller is unit tested and the rendering layer is
  exercised by a headless Streamlit `AppTest` smoke (`tests/test_ui_app_smoke.py`, skipped
  offline in CI); on-screen visual polish is still only checked by the manual checklist.
- `python-dotenv` is declared in `pyproject.toml` but is not imported by any module (config
  reads `os.environ` directly) and is not installed in the verified environment; consider
  wiring `.env` loading or removing the dependency.
- No production Kdenlive project generation exists yet; Phase 6/F is a local
  self-generated editing skeleton only and still requires manual Kdenlive verification.
- C currently generates canonical local files and PNG assets; F now generates a local
  skeleton `project.kdenlive` but does not prove full production edit compatibility.
- No rendering, TTS, voice synthesis, BGM generation, upload, or YouTube workflow exists.
- Smoke uses deterministic fake providers, so it proves local contracts but not provider quality.
- Baseline audit is hand-authored and should be reviewed against the repository tree by GPT Pro.
- Some historical prompt/context material is retained for traceability and may not be as clean as
  the current implementation docs.
- The old `codex/011-github-actions-ci` remote branch still exists and can be cleaned later.
- Optional `llm` dependencies are declared in `pyproject.toml` but intentionally not installed
  by CI or used by source/tests.

## Recommended Next Implementation Slice

The local A->F product scope is implemented (UI, opt-in real adapters, red-team and
multi-sample coverage, and a pinned `requirements.lock.txt`). The next slices are a manual
Kdenlive-open verification pass on real hardware, a fully hashed lock via `uv`/`pip-compile`,
and resolving the declared-but-unused `python-dotenv` dependency.

## GPT Pro Review Notes

- Verify audit inventory against the repository tree.
- Verify state transitions and DB table descriptions against `state_machine.py` and `db.py`.
- Verify CI/protection status through GitHub.
- Verify no real LLM provider, Kdenlive production mutation, render, upload, TTS, or UI scope was
  added by the F skeleton branch.
- Decide whether the next task should be a manual Kdenlive-open smoke checklist or UI.
