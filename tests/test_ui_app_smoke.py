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
