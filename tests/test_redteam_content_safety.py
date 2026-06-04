"""Red-team content-safety coverage for the docs/06 attack categories.

Each test maps to one explicit red-team prompt category from
``docs/06_TEST_PLAN.md`` and asserts that the deterministic B or E guards reject
the adversarial artifact. No real providers, network, or external resources are
used; payloads are constructed in-process and validated through the existing
application-level validators only.

Categories covered:

1. Real-name / nickname inference.
2. Crime-assertion titles.
3. Fabricated numbers or rankings.
4. Direct source / comment quotation.
5. Original-capture reuse.
6. Mockery / demeaning of a specific individual.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from shorts_pipeline.b_service import (
    BScenePlanValidationError,
    generate_b_scene_plan,
    validate_b_scene_plan_against_source,
)
from shorts_pipeline.c_service import compile_c_project
from shorts_pipeline.d_service import (
    assert_d_image_manifest_ready_for_e,
    confirm_d_image_manifest,
)
from shorts_pipeline.e_service import EScriptValidationError, validate_e_script_against_inputs
from shorts_pipeline.llm.validators import ArtifactNotReadyError, assert_manifest_ready_for_e
from shorts_pipeline.models import (
    BScenePlan,
    DImageManifest,
    EScript,
    SourceArtifact,
    TimelineJson,
)
from shorts_pipeline.project_service import create_project_from_candidate

FIXTURES = Path(__file__).parent / "fixtures"


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def load_candidate() -> dict[str, Any]:
    return json.loads((FIXTURES / "sample_source.json").read_text(encoding="utf-8"))


def valid_b_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "sample_b_scene_plan.json").read_text(encoding="utf-8"))


class StaticBProvider:
    provider_name = "fake"
    model_name = "mock-b-scene-plan-v2.1"

    def generate(self, *, source: SourceArtifact, prompt_version: str, previous_errors: list[str]):
        return copy.deepcopy(valid_b_payload())


def _ready_d_payload(timeline: TimelineJson) -> dict[str, Any]:
    return {
        "schema_version": "d_image_manifest.v2.1",
        "project_id": timeline.project_id,
        "image_insert_completed": True,
        "user_confirmed": True,
        "completed_at": None,
        "slots": [
            {
                "slot_id": scene.image_slot_id,
                "scene_id": scene.scene_id,
                "status": "replaced",
                "planned_image_path": scene.image_path,
                "actual_image_path": scene.image_path,
                "actual_image_note": f"User-owned safe abstract image for {scene.scene_id}.",
                "source_type": "user_owned",
                "rights_confirmed_by_user": True,
                "contains_face": False,
                "face_rights_confirmed": None,
                "contains_personal_info": False,
                "contains_original_capture": False,
                "contains_community_logo": False,
                "image_sha256": None,
            }
            for scene in timeline.scenes
        ],
        "warnings": [],
    }


@pytest.fixture(scope="module")
def ready_inputs(tmp_path_factory) -> tuple[SourceArtifact, TimelineJson, DImageManifest]:
    """Build one A->D ready project and return the validated E inputs."""
    base = tmp_path_factory.mktemp("redteam")
    db_path = base / "shorts.sqlite3"
    projects_root = base / "projects"
    project = create_project_from_candidate(
        load_candidate(), db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )
    project_id = project.project_id
    generate_b_scene_plan(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=StaticBProvider(),
        clock=fixed_clock,
    )
    timeline = compile_c_project(
        project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )
    confirm_d_image_manifest(
        project_id,
        _ready_d_payload(timeline),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    source = SourceArtifact.model_validate(
        json.loads((projects_root / project_id / "source.json").read_text(encoding="utf-8"))
    )
    timeline = TimelineJson.model_validate(
        json.loads((projects_root / project_id / "timeline.json").read_text(encoding="utf-8"))
    )
    manifest = assert_d_image_manifest_ready_for_e(
        project_id, db_path=db_path, projects_root=projects_root
    )
    return source, timeline, manifest


def valid_e_payload(timeline: TimelineJson) -> dict[str, Any]:
    paces = ["빠르게", "보통", "느리게", "보통", "빠르게", "보통"]
    narration_script = [
        {
            "scene_id": scene.scene_id,
            "pace": paces[index],
            "script": (
                f"For scene {scene.scene_id}, explain the selected basis safely "
                "without adding unsupported facts."
            ),
            "optional_cut": None,
            "recording_note": "Keep a neutral manual recording tone.",
            "fact_basis": [scene.fact_basis[0]],
        }
        for index, scene in enumerate(timeline.scenes)
    ]
    return {
        "schema_version": "e_script.v2.1",
        "narration_script": narration_script,
        "title_candidates": [
            {"title": "Why this issue caught attention", "angle": "궁금증",
             "fact_safety_note": "Uses only selected summary context."},
            {"title": "The turn people noticed", "angle": "공감/혼란",
             "fact_safety_note": "Does not identify people or quote replies."},
            {"title": "The safer way to read this", "angle": "반전",
             "fact_safety_note": "Avoids unsupported legal claims."},
            {"title": "The point behind the debate", "angle": "분노/논쟁",
             "fact_safety_note": "Frames debate without hard accusations."},
            {"title": "The reaction without the quote", "angle": "밈/반응",
             "fact_safety_note": "Does not reuse raw replies."},
        ],
        "recommended_title": "Why this issue caught attention",
        "forbidden_claims": [
            "real name and nickname inference prohibited",
            "personal information prohibited",
            "crime assertion prohibited",
            "fabricated number prohibited",
            "direct quote from source prohibited",
            "original screenshot reuse prohibited",
        ],
    }


def _set_recommended_title(payload: dict[str, Any], title: str) -> dict[str, Any]:
    payload["title_candidates"][0]["title"] = title
    payload["recommended_title"] = title
    return payload


def _expect_e_rejection(payload: dict[str, Any], inputs) -> None:
    source, timeline, d_manifest = inputs
    script = EScript.model_validate(payload)
    with pytest.raises(EScriptValidationError):
        validate_e_script_against_inputs(
            script, source=source, timeline=timeline, d_manifest=d_manifest
        )


# --- Category 1: real-name / nickname inference -----------------------------


def test_redteam_real_name_in_title_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = _set_recommended_title(valid_e_payload(timeline), "그 사람 실명 공개")
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_nickname_in_narration_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["script"] = "그 사람의 닉네임은 바로 이것입니다."
    _expect_e_rejection(payload, ready_inputs)


# --- Category 2: crime-assertion titles -------------------------------------


def test_redteam_crime_assertion_title_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = _set_recommended_title(valid_e_payload(timeline), "이 사람이 바로 범인")
    _expect_e_rejection(payload, ready_inputs)


# --- Category 3: fabricated numbers / rankings ------------------------------


def test_redteam_fabricated_number_title_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = _set_recommended_title(valid_e_payload(timeline), "Ranked 987654 worldwide")
    _expect_e_rejection(payload, ready_inputs)


# --- Category 4: direct source / comment quotation --------------------------


def test_redteam_direct_comment_quote_in_narration_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["script"] = "댓글에 따르면 상황은 이렇게 흘러갔습니다."
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_b_raw_comment_term_is_blocked(ready_inputs) -> None:
    source, _, _ = ready_inputs
    payload = valid_b_payload()
    payload["scene_plan"][0]["narration_intent"] = "Paste raw comments from the post."
    plan = BScenePlan.model_validate(payload)
    with pytest.raises(BScenePlanValidationError):
        validate_b_scene_plan_against_source(plan, source)


# --- Category 5: original-capture reuse -------------------------------------


def test_redteam_capture_phrase_in_narration_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["script"] = "원문 그대로 캡처를 보면 알 수 있습니다."
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_b_screenshot_term_is_blocked(ready_inputs) -> None:
    source, _, _ = ready_inputs
    payload = valid_b_payload()
    payload["scene_plan"][0]["visual_direction"] = "Reuse the original screenshot capture."
    plan = BScenePlan.model_validate(payload)
    with pytest.raises(BScenePlanValidationError):
        validate_b_scene_plan_against_source(plan, source)


def test_redteam_original_capture_image_blocks_e_readiness(ready_inputs) -> None:
    _, _, manifest = ready_inputs
    data = manifest.model_dump(mode="json")
    data["slots"][0]["contains_original_capture"] = True
    unsafe = DImageManifest.model_validate(data)
    with pytest.raises(ArtifactNotReadyError):
        assert_manifest_ready_for_e(unsafe)


# --- Category 6: mockery / demeaning a specific individual ------------------


def test_redteam_mockery_title_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = _set_recommended_title(valid_e_payload(timeline), "이 사람 진짜 멍청하다")
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_mockery_narration_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["script"] = "저 사람 정말 한심하고 찌질합니다."
    _expect_e_rejection(payload, ready_inputs)


# --- Obfuscation, synonym, and number-grounding bypasses (V2 hardening) -----


def test_redteam_spaced_mockery_is_blocked(ready_inputs) -> None:
    # Inserting spaces between syllables must not slip past the guard.
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["script"] = "저 사람 진짜 멍 청 하네요."
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_zero_width_mockery_title_is_blocked(ready_inputs) -> None:
    # A zero-width space splitting the term must be normalized away and blocked.
    _, timeline, _ = ready_inputs
    payload = _set_recommended_title(
        valid_e_payload(timeline), "이 사람 멍" + chr(0x200B) + "청이"
    )
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_obfuscated_identity_marker_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = _set_recommended_title(valid_e_payload(timeline), "그 사람 실 명 공개")
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_synonym_crime_title_is_blocked(ready_inputs) -> None:
    # A crime synonym not in the original tuple must still be blocked.
    _, timeline, _ = ready_inputs
    payload = _set_recommended_title(valid_e_payload(timeline), "이 사람은 유죄")
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_synonym_mockery_narration_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["script"] = "저 사람 진짜 등신 같습니다."
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_context_absent_number_in_narration_is_blocked(ready_inputs) -> None:
    # Fabricated numbers absent from the safe context must be blocked in narration.
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["script"] = "이 사건은 987654명이 분노했습니다."
    _expect_e_rejection(payload, ready_inputs)


# --- Category 7: fabricated fact-basis grounding (W1) ------------------------


def test_redteam_generic_factbasis_does_not_ground_narration(ready_inputs) -> None:
    # A narration fact_basis of only a generic word must NOT count as connected
    # to the scene (the old generic-term shortcut is removed).
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["fact_basis"] = ["from the timeline"]
    _expect_e_rejection(payload, ready_inputs)


def test_redteam_unrelated_factbasis_is_blocked(ready_inputs) -> None:
    _, timeline, _ = ready_inputs
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["fact_basis"] = ["completely unrelated invented fact"]
    _expect_e_rejection(payload, ready_inputs)
