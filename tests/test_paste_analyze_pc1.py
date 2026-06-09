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
