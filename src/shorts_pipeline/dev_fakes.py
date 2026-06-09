"""Deterministic dev-only fake providers for local smoke runs.

These classes are not real provider adapters. They do not read API keys, import
provider SDKs, or perform network calls.
"""

from __future__ import annotations

import copy
from typing import Any, get_args

from shorts_pipeline.b_service import SAFETY_GUARD_TERMS
from shorts_pipeline.models import (
    NarrationPace,
    ShortsStyle,
    SourceArtifact,
    TimelineJson,
    TitleAngle,
)


class DevFakeBProvider:
    provider_name = "fake"
    model_name = "mock-b-scene-plan-v2.1"

    def __init__(self) -> None:
        self.call_count = 0

    def generate(
        self,
        *,
        source: SourceArtifact,
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        self.call_count += 1
        style = get_args(ShortsStyle)[0]
        payload: dict[str, Any] = {
            "schema_version": "b_scene_plan.v2.1",
            "selected_style": style,
            "style_reason": "A concise issue-summary structure fits this fictional smoke fixture.",
            "target_duration_sec": 34,
            "scene_plan": [
                {
                    "scene_id": "s01",
                    "duration_sec": 8.0,
                    "purpose": "hook",
                    "screen_text": "이거 봤어?",
                    "visual_direction": "Open with a simple question card and neutral background.",
                    "image_slot_description": "Neutral abstract image about a small home tip",
                    "narration_intent": "Raise curiosity without identifying anyone.",
                    "source_basis": ["fictional user summary", "smoke fixture hook"],
                    "do_not_say": [SAFETY_GUARD_TERMS[0], SAFETY_GUARD_TERMS[3]],
                },
                {
                    "scene_id": "s02",
                    "duration_sec": 9.0,
                    "purpose": "context",
                    "screen_text": "상황은 간단해",
                    "visual_direction": "Show a clean summary-card layout with no source capture.",
                    "image_slot_description": "Neutral household object style placeholder",
                    "narration_intent": "Explain the fictional situation from safe metadata only.",
                    "source_basis": ["fictional user summary"],
                    "do_not_say": [SAFETY_GUARD_TERMS[5], SAFETY_GUARD_TERMS[4]],
                },
                {
                    "scene_id": "s03",
                    "duration_sec": 9.0,
                    "purpose": "turn",
                    "screen_text": "반응이 갈렸어",
                    "visual_direction": "Use a balanced split-screen composition.",
                    "image_slot_description": "Abstract image showing two neutral viewpoints",
                    "narration_intent": "Describe the reaction split without amplifying conflict.",
                    "source_basis": ["fictional shortability rationale"],
                    "do_not_say": [SAFETY_GUARD_TERMS[2], SAFETY_GUARD_TERMS[1]],
                },
                {
                    "scene_id": "s04",
                    "duration_sec": 8.0,
                    "purpose": "payoff",
                    "screen_text": "결론만 말할게",
                    "visual_direction": "Close with a restrained conclusion card.",
                    "image_slot_description": "Neutral wrap-up image with no identifiable people",
                    "narration_intent": "End with a cautious summary and no new claims.",
                    "source_basis": ["fictional user risk flags"],
                    "do_not_say": [SAFETY_GUARD_TERMS[3], SAFETY_GUARD_TERMS[5]],
                },
            ],
            "risk_flags": ["identity inference prohibited", "direct quotation prohibited"],
        }
        return copy.deepcopy(payload)


class DevFakeEProvider:
    provider_name = "fake"
    model_name = "mock-e-script-v2.1"

    def __init__(self) -> None:
        self.call_count = 0

    def generate(
        self,
        *,
        context: dict[str, Any],
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        self.call_count += 1
        timeline = TimelineJson.model_validate(context["timeline_json"])
        paces = list(get_args(NarrationPace))
        angles = list(get_args(TitleAngle))
        payload: dict[str, Any] = {
            "schema_version": "e_script.v2.1",
            "narration_script": [
                {
                    "scene_id": scene.scene_id,
                    "pace": paces[index % len(paces)],
                    "script": (
                        f"Scene {scene.scene_id} explains the safe smoke-test basis "
                        "without adding unsupported claims."
                    ),
                    "optional_cut": None,
                    "recording_note": "Record manually in a neutral local-dev tone.",
                    "fact_basis": [scene.fact_basis[0]],
                }
                for index, scene in enumerate(timeline.scenes)
            ],
            "title_candidates": [
                {
                    "title": "왜 이게 화제가 됐을까",
                    "angle": angles[0],
                    "fact_safety_note": "No identity or legal claim is added.",
                },
                {
                    "title": "의외로 단순한 이유",
                    "angle": angles[1],
                    "fact_safety_note": "Only safe summary context is used.",
                },
                {
                    "title": "반응이 갈린 진짜 이유",
                    "angle": angles[2],
                    "fact_safety_note": "No raw replies are quoted.",
                },
                {
                    "title": "조심스럽게 본 결론",
                    "angle": angles[3],
                    "fact_safety_note": "No unsupported facts are added.",
                },
                {
                    "title": "출처 없이 본 반응",
                    "angle": angles[4],
                    "fact_safety_note": "No source quotation is reused.",
                },
            ],
            "recommended_title": "왜 이게 화제가 됐을까",
            "forbidden_claims": [
                "real name and nickname inference prohibited",
                "personal information prohibited",
                "crime assertion prohibited",
                "fabricated number prohibited",
                "direct quote from source prohibited",
                "original screenshot reuse prohibited",
            ],
        }
        return payload
