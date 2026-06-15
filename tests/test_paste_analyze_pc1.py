"""PC1 tests for analyze_pasted_content (copy -> bounded shorts candidate).

Pure local analysis, no network. Verifies title/summary derivation, length
bounds, URL handling, empty-input rejection, and that the full raw text is not
retained verbatim.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from shorts_pipeline.ui import controller as ctrl

_CLOCK = lambda: datetime(2026, 6, 9, 9, 0, 0)  # noqa: E731


def test_analyze_derives_title_and_summary() -> None:
    text = "디시 실베 화제 제목\n\n본문 첫 문단입니다. 두 번째 문장도 있습니다.\n셋째 줄."
    cand = ctrl.analyze_pasted_content(text)
    assert cand.title == "디시 실베 화제 제목"  # first meaningful line
    assert "본문 첫 문단" in cand.excerpt
    assert cand.source == "paste"
    assert cand.url.startswith("https://")  # synthesized placeholder


def test_analyze_uses_supplied_url_when_valid() -> None:
    cand = ctrl.analyze_pasted_content("제목\n본문", source_url="https://gall.dcinside.com/x/123")
    assert cand.url == "https://gall.dcinside.com/x/123"


def test_analyze_ignores_invalid_url() -> None:
    cand = ctrl.analyze_pasted_content("제목\n본문", source_url="not a url")
    assert cand.url.startswith("https://pasted.local/")


def test_analyze_empty_input_raises() -> None:
    with pytest.raises(ValueError):
        ctrl.analyze_pasted_content("   \n\t  ")


def test_analyze_bounds_long_text() -> None:
    long_title = "가" * 500
    long_body = "나" * 5000
    cand = ctrl.analyze_pasted_content(f"{long_title}\n{long_body}")
    assert len(cand.title) <= 80  # title bounded
    assert len(cand.excerpt) <= 500  # summary bounded (no full raw dump)


def test_analyzed_candidate_flows_to_project(tmp_path) -> None:
    config = ctrl.PipelineConfig.from_base_dir(tmp_path)
    cand = ctrl.analyze_pasted_content("붙여넣은 화제 제목\n핵심 요약 내용입니다.")
    candidate = ctrl.draft_candidate_from_discovered(cand.model_dump())
    project = ctrl.create_project(config, candidate, clock=_CLOCK)
    assert ctrl.current_status(config, project.project_id) == "candidate_selected"


def test_long_text_preserves_ending_punchline() -> None:
    # The twist/punchline of a 썰 is usually at the end - it must survive bounding.
    body = "도입부 설명 문장 " * 120  # comfortably > 500 chars before the ending
    text = f"썰 제목\n{body}그리고 마지막에 진짜반전펀치라인이 있었다."
    cand = ctrl.analyze_pasted_content(text)
    assert len(cand.excerpt) <= 500
    assert "진짜반전펀치라인" in cand.excerpt  # ending preserved
    assert "…" in cand.excerpt  # head+tail elision marker


def test_analyze_paste_prompt_distills_and_embeds_text() -> None:
    prompt = ctrl.analyze_paste_prompt("회사에서 있었던 황당한 일\n부장이 어쩌고 저쩌고")
    assert "핵심" in prompt and "JSON" in prompt
    assert "그대로 옮기지" in prompt  # distill, not transcribe
    assert "부장이 어쩌고" in prompt  # the pasted text is embedded for analysis


def test_apply_analyzed_builds_candidate_from_distilled_json() -> None:
    cand = ctrl.apply_analyzed('{"title": "반전 있는 회식 썰", "summary": "실적은 최고인데 회식은 최악"}')
    assert cand.title == "반전 있는 회식 썰"
    assert cand.excerpt == "실적은 최고인데 회식은 최악"
    assert cand.source == "paste"


def test_apply_analyzed_requires_summary() -> None:
    with pytest.raises(ValueError):
        ctrl.apply_analyzed('{"title": "제목만 있음"}')
