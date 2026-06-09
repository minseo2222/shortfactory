"""SH1 tests: the B/E prompts carry a Shorts hook/retention playbook while
keeping the existing safety rules, schema, and outbound minimization intact.
"""

from __future__ import annotations

from shorts_pipeline.llm.manual_paste import build_b_paste_prompt, build_e_paste_prompt
from shorts_pipeline.llm.real_providers import (
    _b_system_prompt,
    _e_system_prompt,
    minimize_b_source,
)
from shorts_pipeline.models import SourceArtifact


def _source() -> SourceArtifact:
    return SourceArtifact(
        schema_version="source.v2.1",
        project_id="PRJ_20260609_0001",
        source_url="https://example.com/post/abc",
        source_community="rss",
        source_title="한국어 화제 제목",
        user_or_llm_summary="한국어 요약 내용입니다.",
        hook="왜 화제일까?",
        why_shortable="짧고 흥미로운 한국어 화제.",
        risk_flags_for_user=[],
        created_at="2026-06-09T09:00:00+09:00",
    )


def test_b_prompt_has_shorts_playbook_and_safety_and_schema() -> None:
    prompt = _b_system_prompt()
    # craft
    assert "훅" in prompt and "오픈 루프" in prompt and "페이싱" in prompt
    # safety preserved
    assert "Never invent numbers" in prompt and "Never mock or demean" in prompt
    # schema preserved
    assert "b_scene_plan.v2.1" in prompt


def test_e_prompt_has_retention_playbook_and_safety() -> None:
    prompt = _e_system_prompt()
    assert "리텐션" in prompt and "recommended_title" in prompt
    assert "Never quote source posts" in prompt
    assert "e_script.v2.1" in prompt


def test_paste_prompt_includes_playbook_but_not_url() -> None:
    prompt = build_b_paste_prompt(_source())
    assert "훅" in prompt  # playbook reached the pasted prompt
    assert "한국어 요약 내용입니다" in prompt  # bounded source still included
    assert "example.com/post/abc" not in prompt  # url still excluded


def test_outbound_minimization_unchanged() -> None:
    minimal = minimize_b_source(_source().model_dump(mode="json"))
    assert set(minimal) == {"source_title", "summary", "hook", "why_shortable", "risk_flags"}
    assert "source_url" not in minimal and "project_id" not in minimal


def test_tone_default_is_jaguk_and_presets_differ() -> None:
    base = build_b_paste_prompt(_source())  # default
    info = build_b_paste_prompt(_source(), tone="정보")
    humor = build_b_paste_prompt(_source(), tone="유머")
    assert "톤=자극적" in base
    assert "톤=정보전달" in info and "톤=자극적" not in info
    assert "톤=유머" in humor
    # safety preserved under every tone
    for prompt in (base, info, humor):
        assert "Never invent numbers" in prompt


def test_unknown_tone_falls_back_to_default() -> None:
    prompt = build_b_paste_prompt(_source(), tone="없는톤")
    assert "톤=자극적" in prompt


def test_e_paste_prompt_builds_with_playbook() -> None:
    context = {
        "timeline_json": {"scenes": [{"scene_id": "s01", "duration_sec": 8.0,
                                       "screen_text": "x", "fact_basis": ["a"], "avoid_claims": []}]},
        "d_image_manifest": {"slots": []},
        "source_reference": {"source_title": "t", "summary": "s", "hook": "h",
                             "why_shortable": "w", "risk_flags_for_user": []},
        "voice_policy": {},
    }
    prompt = build_e_paste_prompt(context)
    assert "리텐션" in prompt and "e_script.v2.1" in prompt
