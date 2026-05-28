from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shorts_pipeline.b_service import validate_b_scene_plan_against_source
from shorts_pipeline.llm.validators import assert_manifest_ready_for_e
from shorts_pipeline.models import (
    BScenePlan,
    CandidateCard,
    DImageManifest,
    DImageSlotManifest,
    EScript,
    SourceArtifact,
    TimelineJson,
)
from shorts_pipeline.projectgen.timeline import build_timeline_from_b_plan

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def source_fixture() -> SourceArtifact:
    return SourceArtifact(
        project_id="PRJ_20260529_0001",
        source_url="https://example.com/community/post/123",
        source_community="example_community",
        source_title="Manual source candidate",
        user_or_llm_summary="A user-written summary of the source idea.",
        hook="A small decision creates a larger conflict.",
        why_shortable="The situation has a clear setup and reversal.",
        risk_flags_for_user=[],
        created_at="2026-05-29T10:30:00+09:00",
    )


def test_candidate_card_valid_fixture_passes() -> None:
    card = CandidateCard.model_validate(load_fixture("sample_source.json"))
    assert card.candidate_id == "cand_001"
    assert card.status == "new"


def test_b_scene_plan_valid_fixture_passes() -> None:
    plan = BScenePlan.model_validate(load_fixture("sample_b_scene_plan.json"))
    assert len(plan.scene_plan) == 4
    assert sum(scene.duration_sec for scene in plan.scene_plan) == 34


def test_b_scene_plan_rejects_nonconsecutive_scene_ids() -> None:
    data = load_fixture("sample_b_scene_plan.json")
    data["scene_plan"][1]["scene_id"] = "s03"
    plan = BScenePlan.model_validate(data)
    with pytest.raises(ValueError):
        validate_b_scene_plan_against_source(plan, source_fixture())


def test_timeline_json_valid_creation_passes() -> None:
    plan = BScenePlan.model_validate(load_fixture("sample_b_scene_plan.json"))
    timeline = build_timeline_from_b_plan(
        plan,
        source=source_fixture(),
        project_id="PRJ_20260529_0001",
    )
    assert isinstance(timeline, TimelineJson)
    assert timeline.total_duration_sec == 34
    assert [scene.start_sec for scene in timeline.scenes] == [0, 8, 17, 26]


def test_timeline_json_rejects_duration_out_of_range() -> None:
    plan = BScenePlan.model_validate(load_fixture("sample_b_scene_plan.json"))
    timeline_data = build_timeline_from_b_plan(
        plan,
        source=source_fixture(),
        project_id="PRJ_20260529_0001",
    ).model_dump()
    timeline_data["scenes"][0]["duration_sec"] = 20
    with pytest.raises(ValidationError):
        TimelineJson.model_validate(timeline_data)


def test_e_script_rejects_recommended_title_outside_candidates() -> None:
    data = {
        "schema_version": "e_script.v2.1",
        "narration_script": [
            {
                "scene_id": "s01",
                "pace": "빠르게",
                "script": "Here is a neutral setup.",
                "optional_cut": None,
                "recording_note": "Use a neutral tone.",
                "fact_basis": ["timeline scene s01"],
            },
            {
                "scene_id": "s02",
                "pace": "보통",
                "script": "Here is safe context.",
                "optional_cut": None,
                "recording_note": "Use a neutral tone.",
                "fact_basis": ["timeline scene s02"],
            },
            {
                "scene_id": "s03",
                "pace": "보통",
                "script": "Here is the safe turn.",
                "optional_cut": None,
                "recording_note": "Use a neutral tone.",
                "fact_basis": ["timeline scene s03"],
            },
            {
                "scene_id": "s04",
                "pace": "느리게",
                "script": "Here is a cautious payoff.",
                "optional_cut": None,
                "recording_note": "Use a neutral tone.",
                "fact_basis": ["timeline scene s04"],
            }
        ],
        "title_candidates": [
            {
                "title": "The Small Choice That Changed Everything",
                "angle": "궁금증",
                "fact_safety_note": "No unsupported claim is added.",
            },
            {
                "title": "Why the Reaction Changed",
                "angle": "공감/혼란",
                "fact_safety_note": "No unsupported claim is added.",
            },
            {
                "title": "A Safer Read on the Issue",
                "angle": "반전",
                "fact_safety_note": "No unsupported claim is added.",
            },
            {
                "title": "The Debate Point",
                "angle": "분노/논쟁",
                "fact_safety_note": "No unsupported claim is added.",
            },
            {
                "title": "The Reaction Without Quotes",
                "angle": "밈/반응",
                "fact_safety_note": "No unsupported claim is added.",
            },
        ],
        "recommended_title": "A Different Unsupported Title",
        "forbidden_claims": ["Do not add unsupported claims."],
    }
    with pytest.raises(ValidationError):
        EScript.model_validate(data)


def test_d_replaced_slot_without_actual_image_note_fails() -> None:
    with pytest.raises(ValidationError):
        DImageSlotManifest(
            slot_id="slot_001",
            scene_id="s01",
            status="replaced",
            planned_image_path="assets/user_images/slot_001.png",
            actual_image_path="assets/user_images/slot_001.png",
            actual_image_note="",
            source_type="user_owned",
            rights_confirmed_by_user=True,
            contains_face=False,
            contains_personal_info=False,
            contains_original_capture=False,
        )


def test_d_manifest_rights_helper_blocks_e_when_rights_missing() -> None:
    manifest = DImageManifest(
        project_id="PRJ_20260529_0001",
        image_insert_completed=True,
        user_confirmed=True,
        completed_at="2026-05-29T10:30:00+09:00",
        slots=[
            {
                "slot_id": f"slot_{index:03d}",
                "scene_id": f"s{index:02d}",
                "status": "placeholder",
                "planned_image_path": f"assets/user_images/slot_{index:03d}.png",
                "actual_image_path": f"assets/user_images/slot_{index:03d}.png",
                "actual_image_note": None,
                "source_type": "app_generated_placeholder",
                "rights_confirmed_by_user": False,
                "contains_face": False,
                "face_rights_confirmed": None,
                "contains_personal_info": False,
                "contains_original_capture": False,
                "contains_community_logo": False,
                "image_sha256": None,
            }
            for index in range(1, 5)
        ],
    )
    with pytest.raises(ValueError):
        assert_manifest_ready_for_e(manifest)
