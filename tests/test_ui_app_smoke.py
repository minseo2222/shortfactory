"""Headless Streamlit smoke test driving app.py through the full A->F flow.

Uses Streamlit's ``AppTest`` to actually execute the rendering layer (not just
the controller), catching runtime errors in the UI itself. A fresh ``AppTest``
is used per stage so that disappearing form widgets do not trip AppTest's
cross-run widget-state bookkeeping; project state persists on disk and in
``session_state['project_id']`` between stages.

The whole module is skipped when the optional ``ui`` extra (Streamlit) is not
installed, so CI stays offline. No network egress occurs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import shorts_pipeline.ui.controller as ctrl  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parents[1] / "src" / "shorts_pipeline" / "ui" / "app.py")


def _fresh(base_dir, project_id: str | None = None) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.session_state["base_dir"] = str(base_dir)
    if project_id is not None:
        at.session_state["project_id"] = project_id
    at.run()
    return at


def _click(at: AppTest, label_substring: str) -> AppTest:
    for button in at.button:
        if label_substring in button.label:
            button.click()
            at.run()
            return at
    raise AssertionError(
        f"button containing {label_substring!r} not found; have {[b.label for b in at.button]}"
    )


def test_ui_app_drives_full_a_to_f(tmp_path) -> None:
    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)

    # A: create a project from the candidate form (defaults are valid).
    at = _click(_fresh(tmp_path), "Create project")
    assert not at.exception
    project_id = at.session_state["project_id"]
    assert ctrl.current_status(cfg, project_id) == "candidate_selected"

    # B -> C: stage buttons.
    at = _click(_fresh(tmp_path, project_id), "scene plan (B)")
    assert not at.exception
    assert ctrl.current_status(cfg, project_id) == "planned"

    at = _click(_fresh(tmp_path, project_id), "timeline and assets (C)")
    assert not at.exception
    assert ctrl.current_status(cfg, project_id) == "project_generated"

    # D: confirm the rights form (defaults keep all slots replaced + confirmed).
    at = _click(_fresh(tmp_path, project_id), "Confirm D")
    assert not at.exception
    assert ctrl.current_status(cfg, project_id) == "images_inserted"

    # E -> F.
    at = _click(_fresh(tmp_path, project_id), "narration and titles (E)")
    assert not at.exception
    assert ctrl.current_status(cfg, project_id) == "script_generated"

    at = _click(_fresh(tmp_path, project_id), "Kdenlive skeleton (F)")
    assert not at.exception

    project_dir = cfg.projects_root / project_id
    assert (project_dir / "project.kdenlive").is_file()
    assert (project_dir / "f_kdenlive_manifest.json").is_file()

    # The F result screen shows the local handoff paths.
    at_final = _fresh(tmp_path, project_id)
    shown = " ".join(block.value for block in at_final.code)
    assert "project.kdenlive" in shown


# --- Error-path coverage (W3) ----------------------------------------------


def _raise(*_args, **_kwargs):
    raise RuntimeError("forced failure")


def test_ui_unknown_project_renders_info_without_crash(tmp_path) -> None:
    at = _fresh(tmp_path, project_id="PRJ_20260101_9999")
    assert not at.exception
    # No status -> the app shows an informational message, not a crash.
    assert any("No UI action" in block.value for block in at.info)


def test_ui_create_failure_renders_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ctrl, "create_project", _raise)
    at = _click(_fresh(tmp_path), "Create project")
    assert not at.exception
    assert any("Create failed" in block.value for block in at.error)


def test_ui_stage_failure_renders_error(tmp_path, monkeypatch) -> None:
    # Create a real project first, then force the B stage to fail.
    at = _click(_fresh(tmp_path), "Create project")
    project_id = at.session_state["project_id"]
    monkeypatch.setattr(ctrl, "run_b", _raise)
    at = _click(_fresh(tmp_path, project_id), "scene plan (B)")
    assert not at.exception
    assert any("failed" in block.value for block in at.error)


# --- U1: one-click full draft + provider readiness panel -------------------


def test_ui_one_click_full_draft_reaches_f(tmp_path) -> None:
    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    at = _click(_fresh(tmp_path), "Generate full draft (A->F)")
    assert not at.exception
    project_id = at.session_state["project_id"]
    assert ctrl.current_status(cfg, project_id) == "script_generated"
    assert (cfg.projects_root / project_id / "project.kdenlive").is_file()


def test_ui_previews_render_after_full_draft(tmp_path) -> None:
    # One-click to F, then a fresh render shows the B/E previews.
    at = _click(_fresh(tmp_path), "Generate full draft (A->F)")
    project_id = at.session_state["project_id"]

    at = _fresh(tmp_path, project_id)
    assert not at.exception
    markdown = " ".join(block.value for block in at.markdown)
    assert "s01" in markdown  # B scene plan preview
    assert any("Recommended title" in block.value for block in at.success)  # E preview


def _candidate(n: int) -> dict:
    return {
        "candidate_id": f"ui-{n}",
        "title": f"Safe fictional title {n}",
        "source_url": f"https://example.com/community/post/{n}",
        "community": "manual",
        "collected_at": "2026-06-01T09:00:00+09:00",
        "summary": "A neutral fictional summary.",
        "hook": "A neutral hook.",
        "why_shortable": "A neutral rationale.",
        "risk_flags_for_user": [],
        "status": "selected",
    }


def test_ui_lists_and_resumes_projects(tmp_path) -> None:
    from datetime import datetime

    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    first = ctrl.create_project(cfg, _candidate(1), clock=lambda: datetime(2026, 6, 4, 9))
    second = ctrl.create_project(cfg, _candidate(2), clock=lambda: datetime(2026, 6, 4, 10))

    at = _fresh(tmp_path)
    labels = [button.label for button in at.button]
    assert any(first.project_id in label for label in labels)
    assert any(second.project_id in label for label in labels)

    at = _click(_fresh(tmp_path), f"Open {first.project_id}")
    assert not at.exception
    assert at.session_state["project_id"] == first.project_id


def test_ui_regenerate_creates_new_project(tmp_path) -> None:
    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    at = _click(_fresh(tmp_path), "Generate full draft (A->F)")
    original = at.session_state["project_id"]

    at = _click(_fresh(tmp_path, original), "Regenerate as new draft")
    assert not at.exception
    new_id = at.session_state["project_id"]
    assert new_id != original
    assert ctrl.current_status(cfg, new_id) == "script_generated"


def test_ui_edit_candidate_returns_to_prefilled_form(tmp_path) -> None:
    at = _click(_fresh(tmp_path), "Generate full draft (A->F)")
    pid = at.session_state["project_id"]

    at = _click(_fresh(tmp_path, pid), "Edit candidate and restart")
    assert not at.exception
    assert "project_id" not in at.session_state
    assert at.session_state["edit_candidate"]["title"]  # candidate stashed for editing


def test_ui_first_run_help_and_stage_hint(tmp_path) -> None:
    # First run (no projects): the how-it-works help is shown.
    at = _fresh(tmp_path)
    assert not at.exception
    help_text = " ".join(block.value for block in at.markdown)
    assert "How this works" in help_text or "finish in Kdenlive" in help_text

    # After creating a project, a per-stage "Next:" hint appears.
    at = _click(_fresh(tmp_path), "Create project")
    project_id = at.session_state["project_id"]
    at = _fresh(tmp_path, project_id)
    assert not at.exception
    assert any("Next:" in block.value for block in at.info)


def test_ui_provider_panel_shows_enable_guidance(tmp_path, monkeypatch) -> None:
    for name in (
        "SHORTS_PIPELINE_ENABLE_REAL_LLM",
        "SHORTS_PIPELINE_LLM_BACKEND",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    at = _fresh(tmp_path)
    assert not at.exception
    guidance = " ".join(block.value for block in at.info)
    assert "SHORTS_PIPELINE_ENABLE_REAL_LLM" in guidance
