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
