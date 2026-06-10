"""CC1 offline tests for the no-API Claude Code / Codex paste bridge.

No network, no key: valid payloads are produced by the deterministic fake
providers and fed back through ``apply_pasted_*`` exactly as a user-pasted CLI
result would be, exercising the same validators.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider
from shorts_pipeline.e_service import build_e_generation_context
from shorts_pipeline.llm.real_providers import OutboundContentError
from shorts_pipeline.models import DImageManifest, SourceArtifact, TimelineJson
from shorts_pipeline.ui import controller as ctrl

_CLOCK = lambda: datetime(2026, 6, 9, 9, 0, 0)  # noqa: E731


def _korean_candidate() -> dict:
    return {
        "candidate_id": "cc-1",
        "title": "한국어 화제 제목",
        "source_url": "https://example.com/post/uniquepath777",
        "community": "rss",
        "collected_at": "2026-06-09T09:00:00+09:00",
        "summary": "한국어 요약 내용입니다. 출처를 직접 인용하지 않습니다.",
        "hook": "왜 이게 화제일까?",
        "why_shortable": "짧고 흥미로운 한국어 화제.",
        "risk_flags_for_user": [],
        "status": "selected",
    }


def _setup(tmp_path):
    config = ctrl.PipelineConfig.from_base_dir(tmp_path)
    project = ctrl.create_project(config, _korean_candidate(), clock=_CLOCK)
    return config, project.project_id


def _load(config, pid, name, model):
    path = config.projects_root / pid / name
    return model.model_validate_json(path.read_text(encoding="utf-8"))


# --- prompt builder ---------------------------------------------------------


def test_b_paste_prompt_has_schema_korean_and_no_url(tmp_path) -> None:
    config, pid = _setup(tmp_path)
    prompt = ctrl.b_paste_prompt(config, pid)
    assert "b_scene_plan.v2.1" in prompt  # schema present
    assert "한국어 요약 내용입니다" in prompt  # bounded Korean source included
    assert "한국어로 작성" in prompt  # Korean output instruction
    assert "uniquepath777" not in prompt  # source_url is dropped by minimization


def test_paste_prompt_refuses_secret_marker_in_summary(tmp_path) -> None:
    config = ctrl.PipelineConfig.from_base_dir(tmp_path)
    bad = _korean_candidate()
    bad["summary"] = "여기 sk-deadbeefsecretkey 가 들어있다"
    project = ctrl.create_project(config, bad, clock=_CLOCK)
    with pytest.raises(OutboundContentError):
        ctrl.b_paste_prompt(config, project.project_id)


# --- apply pasted B ---------------------------------------------------------


def _valid_b_json(config, pid) -> str:
    source = _load(config, pid, "source.json", SourceArtifact)
    payload = DevFakeBProvider().generate(source=source, prompt_version="v", previous_errors=[])
    return json.dumps(payload, ensure_ascii=False)


def test_apply_pasted_b_valid_reaches_planned(tmp_path) -> None:
    config, pid = _setup(tmp_path)
    ctrl.apply_pasted_b(config, pid, _valid_b_json(config, pid), clock=_CLOCK)
    assert ctrl.current_status(config, pid) == "planned"


def test_apply_pasted_b_invalid_json_raises(tmp_path) -> None:
    config, pid = _setup(tmp_path)
    with pytest.raises(ValueError):
        ctrl.apply_pasted_b(config, pid, "이건 JSON이 아니에요 {{{", clock=_CLOCK)


def test_apply_pasted_b_schema_violation_raises(tmp_path) -> None:
    config, pid = _setup(tmp_path)
    with pytest.raises(Exception):  # noqa: B017 - service/pydantic validation rejects it
        ctrl.apply_pasted_b(config, pid, json.dumps({"schema_version": "wrong"}), clock=_CLOCK)


# --- apply pasted E ---------------------------------------------------------


def _to_images_inserted(config, pid) -> None:
    ctrl.apply_pasted_b(config, pid, _valid_b_json(config, pid), clock=_CLOCK)
    timeline = ctrl.run_c(config, pid, clock=_CLOCK)
    ctrl.init_d(config, pid, clock=_CLOCK)
    ctrl.confirm_d(config, pid, ctrl.build_ready_d_payload(timeline), clock=_CLOCK)


def test_e_paste_prompt_and_apply_reach_script_generated(tmp_path) -> None:
    config, pid = _setup(tmp_path)
    _to_images_inserted(config, pid)

    prompt = ctrl.e_paste_prompt(config, pid)
    assert "e_script.v2.1" in prompt and "한국어로 작성" in prompt

    source = _load(config, pid, "source.json", SourceArtifact)
    timeline = _load(config, pid, "timeline.json", TimelineJson)
    manifest = _load(config, pid, "d_image_manifest.json", DImageManifest)
    context = build_e_generation_context(source=source, timeline=timeline, d_manifest=manifest)
    e_payload = DevFakeEProvider().generate(context=context, prompt_version="v", previous_errors=[])

    ctrl.apply_pasted_e(config, pid, json.dumps(e_payload, ensure_ascii=False), clock=_CLOCK)
    assert ctrl.current_status(config, pid) == "script_generated"


def test_apply_pasted_b_heals_missing_do_not_say(tmp_path) -> None:
    # A pasted plan whose scenes omit the (schema-invisible) safety guard must
    # still apply - the bridge injects the required guard instead of failing.
    config, pid = _setup(tmp_path)
    source = _load(config, pid, "source.json", SourceArtifact)
    payload = DevFakeBProvider().generate(source=source, prompt_version="v", previous_errors=[])
    for scene in payload["scene_plan"]:
        scene["do_not_say"] = []
    ctrl.apply_pasted_b(config, pid, json.dumps(payload, ensure_ascii=False), clock=_CLOCK)
    assert ctrl.current_status(config, pid) == "planned"


def test_apply_pasted_e_heals_forbidden_claims(tmp_path) -> None:
    config, pid = _setup(tmp_path)
    _to_images_inserted(config, pid)
    source = _load(config, pid, "source.json", SourceArtifact)
    timeline = _load(config, pid, "timeline.json", TimelineJson)
    manifest = _load(config, pid, "d_image_manifest.json", DImageManifest)
    context = build_e_generation_context(source=source, timeline=timeline, d_manifest=manifest)
    e_payload = DevFakeEProvider().generate(context=context, prompt_version="v", previous_errors=[])
    e_payload["forbidden_claims"] = []  # strip the required category warnings
    ctrl.apply_pasted_e(config, pid, json.dumps(e_payload, ensure_ascii=False), clock=_CLOCK)
    assert ctrl.current_status(config, pid) == "script_generated"
