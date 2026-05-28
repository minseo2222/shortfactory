# 04. GPT Pro and Codex Workflow

## Roles

GPT Pro:

- Product and technical design.
- Specification review.
- Codex task decomposition.
- Codex result review.
- Next Codex prompt generation.

Codex:

- Repository file creation and modification.
- Tests.
- Command execution.
- Result reporting.

## State Storage

Do not rely on chat memory. Store durable context in repository files and Codex
result reports.

Required state locations:

- `docs/`
- `AGENTS.md`
- Test files.
- Codex result report.

## Run Rules

1. GPT Pro creates a narrow `CODEX_PROMPT_XXX`.
2. Codex reads the prompt and repo docs.
3. Codex implements.
4. Codex runs tests.
5. Codex returns a result report.
6. GPT Pro reviews report and diff.
7. GPT Pro writes the next prompt.

## Result Report Fields

- Task ID.
- Summary.
- Files created.
- Files modified.
- Commands run.
- Test results.
- Decisions made.
- Assumptions.
- Known issues or blockers.
- Security and policy check.
- Recommended next task.

## First Run Limits

Do only:

- Repo scaffold.
- Docs.
- DB schema.
- Pydantic models.
- State machine.
- Security helper skeleton.
- Pytest skeleton.

Do not do:

- Real OpenAI, Anthropic, or Gemini API calls.
- Real automated community collection.
- Full Streamlit UI.
- Production-ready Kdenlive XML mutation.
- Automated TTS.
- Automated upload.
