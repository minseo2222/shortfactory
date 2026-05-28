from __future__ import annotations

from pathlib import Path


def test_baseline_audit_doc_has_required_sections_and_claims() -> None:
    audit_path = Path("docs/07_BASELINE_AUDIT.md")
    text = audit_path.read_text(encoding="utf-8")

    required_sections = [
        "# Baseline Repository Audit",
        "## Audit Metadata",
        "## Repository Governance",
        "## Current File Inventory",
        "## Runtime Architecture Summary",
        "## Data Contracts Summary",
        "## Database Schema Summary",
        "## State Machine Summary",
        "## Pipeline Flow Summary",
        "## CLI Surface Summary",
        "## Test Coverage Summary",
        "## Security Boundary Summary",
        "## CI Summary",
        "## Known Risks and Gaps",
        "## Recommended Next Implementation Slice",
        "## GPT Pro Review Notes",
    ]

    assert audit_path.is_file()
    for section in required_sections:
        assert section in text

    for source_file in Path("src/shorts_pipeline").rglob("*.py"):
        assert f"`{source_file.as_posix()}`" in text

    for test_file in Path("tests").rglob("test_*.py"):
        assert f"`{test_file.as_posix()}`" in text

    assert (
        "candidate_selected\n"
        "-> planned\n"
        "-> project_generated\n"
        "-> waiting_for_user_images\n"
        "-> images_inserted\n"
        "-> script_generated"
    ) in text
    assert "pytest and ruff" in text
    assert "No real LLM provider adapter exists yet" in text
    assert "No production Kdenlive project generation exists yet" in text
    assert (
        "No rendering, TTS, voice synthesis, BGM generation, upload, or YouTube workflow exists"
        in text
    )
