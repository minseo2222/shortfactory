# 06. Test Plan

## Unit Tests

- CandidateCard validation.
- BScenePlan validation.
- B provider injection, retry, persistence, and status transition.
- B application validation for scene sequence, duration, source basis, safety
  guards, direct-copy screen text, and raw-source terms.
- TimelineJson validation.
- DImageManifest validation.
- D draft initialization, confirmation, image file validation, rights gate,
  hash verification, and E readiness gate.
- EScript validation, provider injection, retry, persistence, and status
  transition.
- E application validation for narration scene matching, recommended-title
  membership, direct-copy blocking, unsupported numeric titles, hard overclaims,
  forbidden-claims guards, speakability, and raw-source fields.
- FKdenliveManifest validation, deterministic frame calculations, source
  artifact references, safe relative resource paths, and no external-template or
  rendering flags.
- Generated Kdenlive/MLT XML validation for root/profile shape, resource
  existence, safe paths, D image resources, timeline text overlays, and forbidden
  raw-source/API-secret terms.
- State transition validation.
- Safe path validation.
- External URL resource rejection.
- XML escaping helper.

## DB Tests

- Schema init succeeds.
- Foreign keys enabled.
- WAL mode attempted.
- `projects` table exists.
- `artifacts` table exists.
- Invalid project status is rejected by CHECK constraint.

## Timeline Tests

- `start_sec` is assigned by duration accumulation.
- Total duration is computed correctly.
- Scene ID order is preserved.
- Duration out of range fails validation.
- C compile creates `timeline.json`, placeholder image files, user image slots,
  text overlays, and replacement instructions.
- C compile persists timeline/artifact records and transitions status.
- Wrong status and missing/invalid B artifacts fail without C side effects.
- Timeline application validation rejects bad start times, unsafe paths, and
  forbidden raw-source keys.

## D Manifest Tests

- Draft manifest maps timeline scenes to image slots.
- Confirmation computes or verifies SHA-256 hashes.
- Wrong status and missing timeline fail without D side effects.
- Slot mismatch, unsafe paths, missing files, wrong dimensions, missing notes,
  unconfirmed rights, personal information, original captures, face-rights gaps,
  hash mismatches, and forbidden extra fields are rejected.

## Security Tests

- `../evil.png` is rejected.
- `/absolute/path.png` is rejected.
- `https://example.com/a.png` is rejected as a media resource.
- XML special characters are escaped.
- `.env` is not read into logs.

## Integration Tests

- Manual source -> project folder.
- B fixture -> timeline.
- Timeline -> placeholder files.
- D manifest -> E input.
- Local A -> B -> C -> D -> E smoke run reaches `script_generated`.
- Smoke run validates source, B, timeline, D manifest, and E script artifacts.
- Smoke run verifies generated C images, text overlays, guide files, artifact
  SHA-256 records, DB rows, and status history.
- Dev smoke CLI tests cover JSON output, human-readable output, explicit fake
  provider gating, fixed-clock parsing, required path arguments, local directory
  creation, optional `--run-f` F handoff generation, and clean JSON stdout.
- Dev inspect CLI tests cover read-only project lookup, status-event output,
  artifact row output, file/hash verification, strict mode, missing DB/root,
  unknown project IDs, unsafe artifact paths, and clean JSON stdout.
- Dev Kdenlive CLI tests cover explicit local-write confirmation, JSON and
  human output, required arguments, unknown project IDs, wrong project status,
  generated F artifact files, and clean JSON stdout.
- Phase 6/F tests cover Kdenlive skeleton generation after A to E, D-confirmed
  image paths, timeline text overlays, manifest/XML validation, manual editing
  guide safety notes, artifact SHA-256 records, wrong status, missing inputs, D
  readiness failure, unsafe paths, forbidden XML terms, and rollback on write
  failure.
- Optional F smoke tests cover default A to E behavior, explicit F generation
  after E, F artifact checks, status preservation, and failure propagation.
- GitHub Actions CI checks run ruff, pytest, a network/provider import guard,
  and an obvious-secret guard on `main`, `codex/**`, and PRs to `main`.
- Baseline audit doc tests check required sections and key governance, state,
  CI, inventory, and non-goal claims.
- UI controller tests cover the full A->F path, stage-by-stage status
  progression, default-fake/opt-in-real provider selection, status events, and
  D payload construction without importing Streamlit.
- Multi-sample smoke tests run twelve distinct synthetic candidates with varied
  valid scene plans (4-6 scenes, different styles and durations) through the full
  A->F path, asserting `script_generated` status, timeline/narration scene-count
  match, a parseable 1080x1920 30fps `project.kdenlive`, and that every timeline
  and producer media resource exists on disk (no missing media).

## Manual Smoke Tests

### Local UI (Streamlit)

Run `python -m streamlit run src/shorts_pipeline/ui/app.py`, then:

- Set a local working directory in the sidebar; confirm provider mode shows
  `fake` with no opt-in configured.
- Create a project from the A candidate form; confirm status `candidate_selected`.
- Step through B, C, the D rights-confirmation form, E, and F; confirm the
  sidebar status history advances `candidate_selected -> ... -> script_generated`.
- Confirm the F screen prints local `project.kdenlive` and handoff-note paths.
- Confirm no network egress occurs (offline run succeeds).

### Kdenlive open

The automatable parts of the Kdenlive handoff (XML parse, 1080x1920 30fps
profile, and producer/timeline resource existence) are enforced by
`tests/test_multisample_smoke.py` and `tests/test_f_kdenlive_project.py`. The
following GUI steps still require a manual Kdenlive install and run:

- Open `project.kdenlive` in Kdenlive.
- Confirm no missing media.
- Confirm slot image display.
- Confirm text overlay display.
- Confirm `slot_001.png` replacement is reflected.

## Red-Team Tests

Future phases:

- Identity inference attempt.
- Legal-accusation title attempt.
- Unsupported ranking/count attempt.
- Direct comment quotation attempt.
- Original capture reuse attempt.
- Targeted harassment amplification attempt.
