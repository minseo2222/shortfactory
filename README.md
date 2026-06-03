# Shorts Pipeline v2.1

Local MVP for a semi-automated short-form video production pipeline.

The user manually enters a source URL and a short summary. The pipeline stores
only selected project metadata, validates structured LLM-shaped artifacts, and
generates local project files for later manual editing in Kdenlive.

## v2.1 Scope

- Streamlit-based local UI for the A through F flow.
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

## Implemented Scope

The local A through F backend is implemented and covered by tests:

1. Project docs, baseline config, and a pinned `requirements.lock.txt`.
2. A: manual candidate selection to a project row and `source.json`.
3. B: provider-injected scene plan generation, validation, and retry.
4. C: `timeline.json`, placeholder/user-image slots, and text overlay PNGs.
5. D: user image manifest with a rights and safety gate.
6. E: narration and title generation with content-safety guards.
7. F: self-generated local `project.kdenlive` skeleton handoff.
8. A Streamlit local UI and dev CLIs (`smoke`, `inspect`, `generate-kdenlive`).
9. Optional, opt-in real LLM adapters (OpenAI/Anthropic/Gemini), off by default.
10. Focused pytest coverage, including red-team and multi-sample smoke tests.

Real provider API calls, automated image insertion, TTS, upload, and final MP4
rendering remain out of scope by design.

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

## Dependency Lock

`requirements.lock.txt` is a pip `--generate-hashes` style hashed lock (sha256
for every PyPI release file) of the verified core and dev dependency closure.
Install reproducibly with `pip install --require-hashes -r requirements.lock.txt`.
The optional `ui` and `llm` extras are intentionally not pinned there because CI
does not install them. Regenerate with `uv pip compile --generate-hashes` or
`pip-compile --generate-hashes` when those tools are available.

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
