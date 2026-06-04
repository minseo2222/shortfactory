from __future__ import annotations

from pathlib import Path


def test_github_actions_ci_workflow_has_required_checks() -> None:
    workflow_path = Path(".github/workflows/ci.yml")
    text = workflow_path.read_text(encoding="utf-8")

    assert workflow_path.is_file()
    assert "pull_request:" in text
    assert "push:" in text
    assert "- main" in text
    assert '"codex/**"' in text
    assert "actions/checkout@v6" in text
    assert "actions/setup-python@v6" in text
    assert "actions/checkout@v4" not in text
    assert "actions/setup-python@v5" not in text
    assert 'python-version: "3.11"' in text
    assert 'python -m pip install -e ".[dev]"' in text
    assert ".[dev,llm]" not in text
    assert ".[llm]" not in text
    assert "python -m ruff check ." in text
    assert "python -m pytest" in text
    assert "Safety scan for real network/provider imports" in text
    assert "Safety scan for obvious committed secrets" in text
    assert "OPENAI_API_KEY" in text
    assert "ANTHROPIC_API_KEY" in text
    assert "GEMINI_API_KEY" in text
    assert "GOOGLE_API_KEY" in text
    assert "AIza" in text  # Google API key prefix
    assert "sk-[A-Za-z0-9_-]{20,}" in text  # covers sk-, sk-proj-, sk-ant-
