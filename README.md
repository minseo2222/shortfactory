# Shorts Pipeline v2.1

Local MVP for a semi-automated short-form video production pipeline.

The user manually enters a source URL and a short summary. The pipeline stores
only selected project metadata, validates structured LLM-shaped artifacts, and
generates local project files for later manual editing in Kdenlive.

## v2.1 Scope

- Streamlit-based local UI in a later phase.
- SQLite-based project storage.
- Manual URL input only.
- B: structured scene plan generation contract.
- C: canonical `timeline.json` contract.
- C: placeholder image slots and text overlay PNG generation.
- D: user-confirmed image insertion manifest.
- E: narration and title candidate contract.
- F: self-generated local Kdenlive/MLT skeleton handoff from C/D/E artifacts.

## Explicit Non-Goals

- Automated community crawling or scraping by default.
- Login, CAPTCHA, rate-limit, IP rotation, or header spoofing bypasses.
- Storing full source posts or full comments.
- Automated image insertion.
- Automated TTS.
- Automated upload.
- Trusting or mutating external `.kdenlive` files.
- Automatic final MP4 rendering.

## First Implementation Scope

This repository currently implements the first scaffold round:

1. Project docs and baseline config.
2. Python package scaffold.
3. Pydantic data contracts.
4. SQLite schema initialization.
5. Project status state machine.
6. File/resource/XML security helpers.
7. Timeline start-time assignment.
8. Focused pytest coverage.

## Safety Rules

- API keys live only in local environment variables or `.env`; never commit real secrets.
- Do not store full source text, full comments, API keys, secrets, or personal information.
- Keep generated project artifacts under the configured `projects/` root.
- Reject absolute paths, `../` traversal, and external URL media resources.
- Use only self-generated Kdenlive templates and project files.

## F Kdenlive Skeleton

Phase 6/F can generate a local editing handoff from a `script_generated`
project:

- `project.kdenlive`
- `f_kdenlive_manifest.json`
- `notes/manual_kdenlive_editing.md`

The Kdenlive file is self-generated from validated `timeline.json`,
`d_image_manifest.json`, and `e_script.json`. It does not parse or trust
external `.kdenlive` files, render video, run Kdenlive or melt, generate TTS, or
upload anything. The project status remains `script_generated`.

## Local UI

A thin local Streamlit UI drives the manual A through F flow:

```bash
pip install -e ".[ui]"
python -m streamlit run src/shorts_pipeline/ui/app.py
```

The UI calls only the existing phase services through a Streamlit-free
controller (`src/shorts_pipeline/ui/controller.py`). It performs no network
egress: B and E use the deterministic fake providers unless the explicit
real-LLM opt-in (`SHORTS_PIPELINE_ENABLE_REAL_LLM` plus
`SHORTS_PIPELINE_LLM_BACKEND`) is configured. It does not render video, run TTS,
upload, or trust external `.kdenlive` files.

## Dev Smoke CLI

Run the local backend smoke path with explicit fake providers:

```bash
python -m shorts_pipeline.dev_cli smoke \
  --db-path ./.local/shorts_pipeline.sqlite3 \
  --projects-root ./.local/projects \
  --use-fake-providers \
  --fixed-clock 2026-05-28T09:00:00+09:00 \
  --json
```

This is a local developer check only. It uses deterministic fake providers and
does not call real APIs, scrape, download images, render, upload, run TTS, or
mutate production Kdenlive XML.

Optionally run Phase F after E and verify the local Kdenlive handoff artifacts:

```bash
shorts-pipeline-dev smoke \
  --db-path ./.local/shorts_pipeline.sqlite3 \
  --projects-root ./.local/projects \
  --use-fake-providers \
  --run-f
```

Default smoke remains A to E and ends at `script_generated`. `--run-f`
additionally generates and verifies `project.kdenlive`,
`f_kdenlive_manifest.json`, and `notes/manual_kdenlive_editing.md`. It does not
render, run Kdenlive or melt, generate TTS, upload, call providers, or trust
external `.kdenlive` files.

Inspect an existing local project without mutating DB rows or files:

```bash
python -m shorts_pipeline.dev_cli inspect \
  --db-path ./.local/shorts_pipeline.sqlite3 \
  --projects-root ./.local/projects \
  --project-id PRJ_20260528_0001 \
  --json
```

The inspect command is read-only. It does not run smoke, call fake or real
providers, render, upload, or mutate Kdenlive XML.

## Dev Kdenlive Skeleton CLI

Generate local F editing handoff artifacts for an existing `script_generated`
project:

```bash
shorts-pipeline-dev generate-kdenlive \
  --db-path ./.local/shorts_pipeline.sqlite3 \
  --projects-root ./.local/projects \
  --project-id PRJ_YYYYMMDD_0001 \
  --confirm-local-write
```

This writes `project.kdenlive`, `f_kdenlive_manifest.json`, and
`notes/manual_kdenlive_editing.md`. It does not render, run Kdenlive or melt,
generate TTS, upload, call providers, or trust external `.kdenlive` files.

## CI

GitHub Actions runs the local test suite and lint checks on `main`, `codex/**`
branch pushes, and pull requests to `main`.

CI runs:

```bash
python -m ruff check .
python -m pytest
```

It installs only the package plus dev dependencies. It does not install LLM
provider extras, call real APIs, scrape, render, upload, or mutate production
Kdenlive XML.

## Baseline Audit

The protected-main repository baseline is summarized in
[`docs/07_BASELINE_AUDIT.md`](docs/07_BASELINE_AUDIT.md).

## Dev GitHub Workflow

Initial repository state is pushed to `main`.

For future Codex tasks:

1. Start from `origin/main`.
2. Create a task branch named `codex/<task-id>-short-title`.
3. Make only the requested changes.
4. Run:

   ```bash
   python -m pytest
   python -m ruff check .
   ```

5. Commit with a clear message.
6. Push the branch.
7. Report the branch name, base SHA, head SHA, compare URL or PR URL, test
   results, and security/policy checklist.

Do not commit local runtime data, secrets, generated videos, local DB files, or
`.local/`.
