"""Tests for the merged variant tone presets.

The 50 researched variant presets are merged into TONE_PRESETS without
displacing the base tones (자극적 stays default), every preset keeps the
"톤=..." format, and a selected variant flows into the exported prompt.
"""

from __future__ import annotations

from shorts_pipeline.llm.manual_paste import (
    DEFAULT_TONE,
    TONE_PRESETS,
    build_b_paste_prompt,
)
from shorts_pipeline.llm.real_providers import SourceArtifact
from shorts_pipeline.llm.tone_variants import VARIANT_TONE_PRESETS
from shorts_pipeline.ui import controller as ctrl


def _source() -> SourceArtifact:
    return SourceArtifact(
        schema_version="source.v2.1",
        project_id="PRJ_20260610_0001",
        source_url="https://example.com/p/1",
        source_community="rss",
        source_title="화제 제목",
        user_or_llm_summary="요약 내용입니다.",
        hook="왜?",
        why_shortable="흥미로운 한국어 화제.",
        risk_flags_for_user=[],
        created_at="2026-06-10T09:00:00+09:00",
    )


def test_all_variants_merged_without_displacing_base() -> None:
    assert len(VARIANT_TONE_PRESETS) == 50
    assert DEFAULT_TONE == "자극적" and TONE_PRESETS["자극적"].startswith("톤=자극적")
    # base + variants all present
    for name in ("자극적", "커뮤니티(반말·밈)", "정보", "유머", "감성"):
        assert name in TONE_PRESETS
    for name in ("썰개그", "사이다서사", "가짜다큐체", "소름미스터리"):
        assert name in TONE_PRESETS


def test_every_preset_keeps_format() -> None:
    for name, instruction in TONE_PRESETS.items():
        assert instruction.startswith("톤="), name
        assert instruction.strip()


def test_shorts_tones_lists_variants_default_first() -> None:
    tones = ctrl.shorts_tones()
    assert tones[0] == "자극적"
    assert "썰개그" in tones and "밸런스게임진행" in tones
    assert len(tones) >= 55


def test_selected_variant_reaches_prompt() -> None:
    prompt = build_b_paste_prompt(_source(), tone="썰개그")
    assert "톤=썰개그" in prompt
    # safety block still present under a variant tone
    assert "Never invent numbers" in prompt
