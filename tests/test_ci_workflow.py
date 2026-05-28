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
