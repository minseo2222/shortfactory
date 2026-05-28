# Codex Operating Rules

Codex owns repository implementation, tests, command execution, and result
reporting. GPT Pro owns design review and next-prompt generation.

## Baseline Documents

Before changing behavior in this repo, read:

1. `README.md`
2. `docs/00_PROJECT_BRIEF.md`
3. `docs/01_ARCHITECTURE.md`
4. `docs/02_DATA_CONTRACTS.md`
5. `docs/03_SECURITY_POLICY.md`
6. `docs/05_PHASE_PLAN.md`
7. `docs/06_TEST_PLAN.md`

## Hard Boundaries

- Do not enable automated community crawling by default.
- Do not store full source posts or full comments.
- Do not store or log API keys or secrets.
- Do not trust or mutate external `.kdenlive` files.
- Do not put absolute paths, `../`, or external URL resources into project artifacts.
- Do not implement automated TTS, upload, or image insertion in the first scope.
- Do not implement login, CAPTCHA, IP rotation, header spoofing, or rate-limit bypasses.

## Implementation Principles

- Keep changes small and contract-driven.
- Validate JSON artifacts through Pydantic before storing them.
- Use helper functions for date/time instead of hard-coded timestamps.
- Put ambiguous decisions into result-report assumptions.

## End-of-Run Report

Report:

- Created and modified files.
- Commands run.
- Test results.
- Decisions and assumptions.
- Known issues or blockers.
- Security and policy checklist.
- Recommended next task.

## GitHub Diff Workflow

After the initial `main` push, do not commit directly to `main` for future
Codex tasks. Start from the latest `origin/main`, create
`codex/<task-id>-short-title`, keep the change scoped to the requested task,
run `python -m pytest` and `python -m ruff check .`, commit, push the branch,
and report the base SHA, head SHA, branch, compare URL or PR URL, and test
results.
