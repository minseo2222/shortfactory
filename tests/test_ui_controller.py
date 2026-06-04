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

import pytest

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


def _clear_llm_env(monkeypatch) -> None:
    for name in (
        "SHORTS_PIPELINE_ENABLE_REAL_LLM",
        "SHORTS_PIPELINE_LLM_BACKEND",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_readiness_fake_when_unconfigured(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    info = ctrl.readiness()
    assert info["mode"] == "fake"
    assert info["ready"] is False
    assert info["key_present"] is False
    # The enable flag name must be surfaced as actionable guidance.
    assert any("SHORTS_PIPELINE_ENABLE_REAL_LLM" in item for item in info["missing"])


def test_readiness_real_selected_but_missing_key(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("SHORTS_PIPELINE_ENABLE_REAL_LLM", "1")
    monkeypatch.setenv("SHORTS_PIPELINE_LLM_BACKEND", "anthropic")
    info = ctrl.readiness()
    assert info["mode"] == "real:anthropic"  # attempted...
    assert info["ready"] is False  # ...but not fully configured
    assert any("ANTHROPIC_API_KEY" in item for item in info["missing"])


def test_readiness_ready_with_key_never_leaks_value(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("SHORTS_PIPELINE_ENABLE_REAL_LLM", "1")
    monkeypatch.setenv("SHORTS_PIPELINE_LLM_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    info = ctrl.readiness()
    assert info["ready"] is True
    assert info["key_present"] is True
    assert info["missing"] == []
    # The secret value must never appear anywhere in the readiness summary.
    assert "sk-super-secret-value" not in repr(info)


def test_artifact_loaders_return_none_then_value(tmp_path) -> None:
    config = make_config(tmp_path)
    project = ctrl.create_project(config, candidate(), clock=fixed_clock)
    pid = project.project_id

    assert ctrl.load_b_plan(config, pid) is None
    assert ctrl.load_timeline(config, pid) is None
    assert ctrl.load_e_script(config, pid) is None
    assert ctrl.load_f_manifest(config, pid) is None

    ctrl.run_b(config, pid, clock=fixed_clock)
    plan = ctrl.load_b_plan(config, pid)
    assert plan is not None and len(plan.scene_plan) >= 1

    ctrl.run_c(config, pid, clock=fixed_clock)
    timeline = ctrl.load_timeline(config, pid)
    assert timeline is not None and len(timeline.scenes) == len(plan.scene_plan)
    assert ctrl.load_e_script(config, pid) is None  # not generated yet


_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _project_with_timeline(tmp_path):
    config = make_config(tmp_path)
    project = ctrl.create_project(config, candidate(), clock=fixed_clock)
    ctrl.run_b(config, project.project_id, clock=fixed_clock)
    timeline = ctrl.run_c(config, project.project_id, clock=fixed_clock)
    return config, project.project_id, timeline


def test_store_user_image_writes_valid_png(tmp_path) -> None:
    config, pid, timeline = _project_with_timeline(tmp_path)
    slot_path = timeline.scenes[0].image_path
    rel = ctrl.store_user_image(config, pid, slot_path, _PNG_BYTES, filename="my_photo.png")
    assert rel == slot_path
    written = config.projects_root / pid / rel
    assert written.read_bytes() == _PNG_BYTES


def test_store_user_image_rejects_bad_extension(tmp_path) -> None:
    config, pid, timeline = _project_with_timeline(tmp_path)
    with pytest.raises(ctrl.UserImageError):
        ctrl.store_user_image(
            config, pid, timeline.scenes[0].image_path, _PNG_BYTES, filename="evil.exe"
        )


def test_store_user_image_rejects_oversize(tmp_path, monkeypatch) -> None:
    config, pid, timeline = _project_with_timeline(tmp_path)
    monkeypatch.setattr(ctrl, "MAX_USER_IMAGE_BYTES", 4)
    with pytest.raises(ctrl.UserImageError):
        ctrl.store_user_image(
            config, pid, timeline.scenes[0].image_path, b"12345", filename="big.png"
        )


def test_store_user_image_rejects_empty(tmp_path) -> None:
    config, pid, timeline = _project_with_timeline(tmp_path)
    with pytest.raises(ctrl.UserImageError):
        ctrl.store_user_image(
            config, pid, timeline.scenes[0].image_path, b"", filename="empty.png"
        )


def test_store_user_image_rejects_path_traversal(tmp_path) -> None:
    config, pid, _ = _project_with_timeline(tmp_path)
    with pytest.raises(ctrl.UserImageError):
        ctrl.store_user_image(config, pid, "../escape.png", _PNG_BYTES, filename="ok.png")


def test_list_projects_newest_first(tmp_path) -> None:
    config = make_config(tmp_path)
    assert ctrl.list_projects(config) == []  # no DB yet

    older = ctrl.create_project(config, candidate(), clock=lambda: datetime(2026, 6, 4, 9, 0, 0))
    newer = ctrl.create_project(config, candidate(), clock=lambda: datetime(2026, 6, 4, 10, 0, 0))

    summaries = ctrl.list_projects(config)
    ids = [s.project_id for s in summaries]
    assert older.project_id in ids and newer.project_id in ids
    assert ids[0] == newer.project_id  # newest first
    assert all(s.status for s in summaries)
    assert all(s.title for s in summaries)


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
