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
- Dev project verifier tests cover read-only A to E and required-F verification,
  JSON contract checks, F XML validation, artifact row and SHA-256 checks,
  missing artifacts, unsafe artifact rows, hash mismatches, CLI JSON/human
  output, and non-mutating failure reports.
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

Future phases:

- Multi-sample smoke runs.

## Manual Smoke Tests

Future phases:

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
