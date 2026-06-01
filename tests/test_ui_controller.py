"""Tests for the Streamlit-free UI orchestration controller.

These exercise the full A->F path through the controller with the default fake
providers (no network), plus provider selection and the D payload builder. The
Streamlit ``app.py`` layer is verified manually per docs/06; it is intentionally
not imported here because the optional ``ui`` extra is not installed in CI.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider
from shorts_pipeline.llm.real_providers import RealBScenePlanProvider, RealEScriptProvider
from shorts_pipeline.models import EScript, FKdenliveManifest
from shorts_pipeline.ui import controller as ctrl

FIXTURES = Path(__file__).parent / "fixtures"


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def candidate() -> dict:
    return json.loads((FIXTURES / "sample_source.json").read_text(encoding="utf-8"))


def make_config(tmp_path) -> ctrl.PipelineConfig:
    return ctrl.PipelineConfig.from_base_dir(tmp_path)


def test_full_pipeline_reaches_script_generated_and_writes_f(tmp_path) -> None:
    config = make_config(tmp_path)
    result = ctrl.run_full_pipeline(config, candidate(), clock=fixed_clock)

    assert result["status"] == "script_generated"
    assert isinstance(result["script"], EScript)
    assert isinstance(result["f_manifest"], FKdenliveManifest)
    project_dir = config.projects_root / result["project_id"]
    assert (project_dir / "project.kdenlive").is_file()
    assert (project_dir / "f_kdenlive_manifest.json").is_file()
    assert (project_dir / "notes" / "manual_kdenlive_editing.md").is_file()
    assert (project_dir / "e_script.json").is_file()


def test_stage_by_stage_status_progression(tmp_path) -> None:
    config = make_config(tmp_path)
    project = ctrl.create_project(config, candidate(), clock=fixed_clock)
    pid = project.project_id
    assert ctrl.current_status(config, pid) == "candidate_selected"

    ctrl.run_b(config, pid, clock=fixed_clock)
    assert ctrl.current_status(config, pid) == "planned"

    timeline = ctrl.run_c(config, pid, clock=fixed_clock)
    assert ctrl.current_status(config, pid) == "project_generated"

    ctrl.init_d(config, pid, clock=fixed_clock)
    assert ctrl.current_status(config, pid) == "waiting_for_user_images"

    payload = ctrl.build_ready_d_payload(timeline)
    ctrl.confirm_d(config, pid, payload, clock=fixed_clock)
    assert ctrl.current_status(config, pid) == "images_inserted"

    ctrl.run_e(config, pid, clock=fixed_clock)
    assert ctrl.current_status(config, pid) == "script_generated"

    ctrl.run_f(config, pid, clock=fixed_clock)
    assert ctrl.current_status(config, pid) == "script_generated"


def test_current_status_is_none_for_missing_project(tmp_path) -> None:
    config = make_config(tmp_path)
    assert ctrl.current_status(config, "PRJ_20260529_9999") is None


def test_status_events_recorded_through_pipeline(tmp_path) -> None:
    config = make_config(tmp_path)
    result = ctrl.run_full_pipeline(config, candidate(), clock=fixed_clock)
    events = ctrl.status_events(config, result["project_id"])
    to_states = [event.to_status for event in events]
    for expected in [
        "candidate_selected",
        "planned",
        "project_generated",
        "waiting_for_user_images",
        "images_inserted",
        "script_generated",
    ]:
        assert expected in to_states


def test_provider_mode_defaults_to_fake(monkeypatch) -> None:
    monkeypatch.delenv("SHORTS_PIPELINE_ENABLE_REAL_LLM", raising=False)
    monkeypatch.delenv("SHORTS_PIPELINE_LLM_BACKEND", raising=False)
    assert ctrl.provider_mode() == "fake"
    assert isinstance(ctrl.select_b_provider(), DevFakeBProvider)
    assert isinstance(ctrl.select_e_provider(), DevFakeEProvider)


def test_provider_mode_real_when_opted_in(monkeypatch) -> None:
    monkeypatch.setenv("SHORTS_PIPELINE_ENABLE_REAL_LLM", "1")
    monkeypatch.setenv("SHORTS_PIPELINE_LLM_BACKEND", "openai")
    assert ctrl.provider_mode() == "real:openai"
    # Construction is lazy; selecting a real provider must not require an SDK.
    assert isinstance(ctrl.select_b_provider(), RealBScenePlanProvider)
    assert isinstance(ctrl.select_e_provider(), RealEScriptProvider)


def test_build_ready_d_payload_applies_overrides(tmp_path) -> None:
    config = make_config(tmp_path)
    project = ctrl.create_project(config, candidate(), clock=fixed_clock)
    ctrl.run_b(config, project.project_id, clock=fixed_clock)
    timeline = ctrl.run_c(config, project.project_id, clock=fixed_clock)
    first_scene = timeline.scenes[0].scene_id

    payload = ctrl.build_ready_d_payload(
        timeline, slot_inputs={first_scene: {"actual_image_note": "Custom note."}}
    )
    first_slot = next(slot for slot in payload["slots"] if slot["scene_id"] == first_scene)
    assert first_slot["actual_image_note"] == "Custom note."
    assert first_slot["rights_confirmed_by_user"] is True
