from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from shorts_pipeline.b_service import generate_b_scene_plan
from shorts_pipeline.c_service import compile_c_project
from shorts_pipeline.d_service import (
    assert_d_image_manifest_ready_for_e,
    confirm_d_image_manifest,
    initialize_d_image_manifest,
)
from shorts_pipeline.db import connect_db
from shorts_pipeline.e_service import (
    EScriptGenerationError,
    EScriptValidationError,
    ProjectStatusError,
    ProviderNotConfiguredError,
    generate_e_script,
    validate_e_script_against_inputs,
)
from shorts_pipeline.models import DImageManifest, EScript, SourceArtifact, TimelineJson
from shorts_pipeline.project_service import create_project_from_candidate
from shorts_pipeline.security import sha256_file

FIXTURES = Path(__file__).parent / "fixtures"
FORBIDDEN_E_TERMS = {
    "full_text",
    "comments",
    "raw_html",
    "api_key",
    "secret",
}


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def load_candidate() -> dict[str, Any]:
    return json.loads((FIXTURES / "sample_source.json").read_text(encoding="utf-8"))


def valid_b_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "sample_b_scene_plan.json").read_text(encoding="utf-8"))


class StaticBProvider:
    provider_name = "fake"
    model_name = "mock-b-scene-plan-v2.1"

    def generate(
        self,
        *,
        source: SourceArtifact,
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        return copy.deepcopy(valid_b_payload())


class SequenceEProvider:
    provider_name = "fake"
    model_name = "mock-e-script-v2.1"

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.call_count = 0
        self.previous_errors_by_call: list[list[str]] = []
        self.contexts: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        context: dict[str, Any],
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        self.call_count += 1
        self.previous_errors_by_call.append(list(previous_errors))
        self.contexts.append(copy.deepcopy(context))
        index = min(self.call_count - 1, len(self.payloads) - 1)
        return copy.deepcopy(self.payloads[index])


def create_selected_project(tmp_path) -> tuple[Path, Path, str]:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    project = create_project_from_candidate(
        load_candidate(),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    return db_path, projects_root, project.project_id


def create_generated_project(tmp_path) -> tuple[Path, Path, str, TimelineJson]:
    db_path, projects_root, project_id = create_selected_project(tmp_path)
    generate_b_scene_plan(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=StaticBProvider(),
        clock=fixed_clock,
    )
    timeline = compile_c_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    return db_path, projects_root, project_id, timeline


def ready_payload_from_timeline(timeline: TimelineJson) -> dict[str, Any]:
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


def create_ready_project(tmp_path) -> tuple[Path, Path, str, TimelineJson, DImageManifest]:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    manifest = confirm_d_image_manifest(
        project_id,
        ready_payload_from_timeline(timeline),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    return db_path, projects_root, project_id, timeline, manifest


def fetch_one(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row:
    conn = connect_db(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def fetch_count(db_path: Path, table: str, where: str = "1 = 1") -> int:
    conn = connect_db(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
    finally:
        conn.close()


def project_status(db_path: Path, project_id: str) -> str:
    return fetch_one(db_path, "SELECT status FROM projects WHERE id = ?", (project_id,))["status"]


def source_from_project(projects_root: Path, project_id: str) -> SourceArtifact:
    data = json.loads((projects_root / project_id / "source.json").read_text(encoding="utf-8"))
    return SourceArtifact.model_validate(data)


def timeline_from_project(projects_root: Path, project_id: str) -> TimelineJson:
    data = json.loads((projects_root / project_id / "timeline.json").read_text(encoding="utf-8"))
    return TimelineJson.model_validate(data)


def e_path(projects_root: Path, project_id: str) -> Path:
    return projects_root / project_id / "e_script.json"


def valid_e_payload(timeline: TimelineJson) -> dict[str, Any]:
    paces = ["빠르게", "보통", "느리게", "보통", "빠르게", "보통"]
    narration_script = []
    for index, scene in enumerate(timeline.scenes):
        narration_script.append(
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
        )
    return {
        "schema_version": "e_script.v2.1",
        "narration_script": narration_script,
        "title_candidates": [
            {
                "title": "Why this issue caught attention",
                "angle": "궁금증",
                "fact_safety_note": "Uses only selected summary context.",
            },
            {
                "title": "The turn people noticed",
                "angle": "공감/혼란",
                "fact_safety_note": "Does not identify people or quote user replies.",
            },
            {
                "title": "The safer way to read this",
                "angle": "반전",
                "fact_safety_note": "Avoids unsupported legal claims.",
            },
            {
                "title": "The point behind the debate",
                "angle": "분노/논쟁",
                "fact_safety_note": "Frames debate without hard accusations.",
            },
            {
                "title": "The reaction without the quote",
                "angle": "밈/반응",
                "fact_safety_note": "Does not reuse raw replies.",
            },
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


def load_e_inputs(
    db_path: Path,
    projects_root: Path,
    project_id: str,
) -> tuple[SourceArtifact, TimelineJson, DImageManifest]:
    source = source_from_project(projects_root, project_id)
    timeline = timeline_from_project(projects_root, project_id)
    manifest = assert_d_image_manifest_ready_for_e(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
    )
    return source, timeline, manifest


def test_happy_path_generates_e_script_file_db_and_status(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    provider = SequenceEProvider([valid_e_payload(timeline)])

    script = generate_e_script(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=provider,
        clock=fixed_clock,
    )

    assert isinstance(script, EScript)
    path = e_path(projects_root, project_id)
    assert path.is_file()
    reloaded = EScript.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert [line.scene_id for line in reloaded.narration_script] == [
        scene.scene_id for scene in timeline.scenes
    ]
    assert reloaded.recommended_title in {title.title for title in reloaded.title_candidates}
    serialized = json.dumps(reloaded.model_dump(mode="json")).casefold()
    assert all(term not in serialized for term in FORBIDDEN_E_TERMS)
    assert project_status(db_path, project_id) == "script_generated"

    script_row = fetch_one(db_path, "SELECT * FROM scripts WHERE project_id = ?", (project_id,))
    assert script_row["schema_version"] == "e_script.v2.1"
    assert script_row["artifact_path"] == f"{project_id}/e_script.json"
    assert script_row["recommended_title"] == reloaded.recommended_title
    assert script_row["llm_run_id"] is not None
    assert len(json.loads(script_row["narration_json"])) == len(timeline.scenes)

    artifact = fetch_one(
        db_path,
        "SELECT * FROM artifacts WHERE project_id = ? AND artifact_type = ?",
        (project_id, "e_script"),
    )
    assert artifact["relative_path"] == f"{project_id}/e_script.json"
    assert not Path(artifact["relative_path"]).is_absolute()
    assert ".." not in Path(artifact["relative_path"]).parts
    assert artifact["sha256"] == sha256_file(path)

    llm_run = fetch_one(
        db_path,
        "SELECT * FROM llm_runs WHERE project_id = ? AND stage = ?",
        (project_id, "E"),
    )
    assert llm_run["provider"] == "fake"
    assert llm_run["model_name"] == "mock-e-script-v2.1"
    assert llm_run["prompt_version"] == "e_script_prompt.v2.1.001"
    assert llm_run["schema_version"] == "e_script.v2.1"
    assert llm_run["status"] == "succeeded"
    assert provider.contexts[0]["project_id"] == project_id


def test_d_readiness_is_required_before_e_generation(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)

    with pytest.raises(ProjectStatusError):
        generate_e_script(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            provider=SequenceEProvider([valid_e_payload(timeline)]),
            clock=fixed_clock,
        )

    assert not e_path(projects_root, project_id).exists()
    assert fetch_count(db_path, "scripts") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type = 'e_script'") == 0
    assert project_status(db_path, project_id) == "waiting_for_user_images"


def test_no_provider_means_no_network_fallback_or_status_change(tmp_path) -> None:
    db_path, projects_root, project_id, _timeline, _manifest = create_ready_project(tmp_path)

    with pytest.raises(ProviderNotConfiguredError):
        generate_e_script(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            provider=None,
            clock=fixed_clock,
        )

    assert not e_path(projects_root, project_id).exists()
    assert fetch_count(db_path, "scripts") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type = 'e_script'") == 0
    assert project_status(db_path, project_id) == "images_inserted"


def test_retry_succeeds_after_invalid_first_response(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    invalid_payload = valid_e_payload(timeline)
    invalid_payload["recommended_title"] = "Not in candidates"
    provider = SequenceEProvider([invalid_payload, valid_e_payload(timeline)])

    generate_e_script(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=provider,
        clock=fixed_clock,
    )

    assert provider.call_count == 2
    assert provider.previous_errors_by_call[0] == []
    assert provider.previous_errors_by_call[1]
    assert e_path(projects_root, project_id).is_file()
    assert fetch_count(db_path, "scripts") == 1
    assert fetch_count(db_path, "artifacts", "artifact_type = 'e_script'") == 1
    assert project_status(db_path, project_id) == "script_generated"


def test_retry_exhaustion_leaves_no_e_state(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    invalid_payload = valid_e_payload(timeline)
    invalid_payload["recommended_title"] = "Not in candidates"
    provider = SequenceEProvider([invalid_payload])

    with pytest.raises(EScriptGenerationError):
        generate_e_script(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            provider=provider,
            clock=fixed_clock,
            max_retries=2,
        )

    assert provider.call_count == 3
    assert not e_path(projects_root, project_id).exists()
    assert fetch_count(db_path, "scripts") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type = 'e_script'") == 0
    assert project_status(db_path, project_id) == "images_inserted"


def test_narration_scene_mismatch_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    source, timeline, d_manifest = load_e_inputs(db_path, projects_root, project_id)
    payload = valid_e_payload(timeline)
    payload["narration_script"][1]["scene_id"], payload["narration_script"][2]["scene_id"] = (
        payload["narration_script"][2]["scene_id"],
        payload["narration_script"][1]["scene_id"],
    )
    script = EScript.model_validate(payload)

    with pytest.raises(EScriptValidationError):
        validate_e_script_against_inputs(
            script,
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
        )


def test_recommended_title_mismatch_is_blocked(tmp_path) -> None:
    _db_path, _projects_root, _project_id, timeline, _manifest = create_ready_project(tmp_path)
    payload = valid_e_payload(timeline)
    payload["recommended_title"] = "Candidate list does not include this"

    with pytest.raises(ValidationError):
        EScript.model_validate(payload)


def test_direct_copy_title_or_script_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    source, timeline, d_manifest = load_e_inputs(db_path, projects_root, project_id)
    payload = valid_e_payload(timeline)
    payload["title_candidates"][0]["title"] = "Manual source candidate"
    payload["recommended_title"] = "Manual source candidate"
    script = EScript.model_validate(payload)

    with pytest.raises(EScriptValidationError):
        validate_e_script_against_inputs(
            script,
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
        )


def test_unsupported_numeric_title_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    source, timeline, d_manifest = load_e_inputs(db_path, projects_root, project_id)
    payload = valid_e_payload(timeline)
    payload["title_candidates"][0]["title"] = "Shocking 999 person story"
    payload["recommended_title"] = "Shocking 999 person story"
    script = EScript.model_validate(payload)

    with pytest.raises(EScriptValidationError):
        validate_e_script_against_inputs(
            script,
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
        )


def test_hard_overclaim_title_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    source, timeline, d_manifest = load_e_inputs(db_path, projects_root, project_id)
    payload = valid_e_payload(timeline)
    payload["title_candidates"][0]["title"] = "Criminal confirmed"
    payload["recommended_title"] = "Criminal confirmed"
    script = EScript.model_validate(payload)

    with pytest.raises(EScriptValidationError):
        validate_e_script_against_inputs(
            script,
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
        )


def test_missing_forbidden_claims_safety_guard_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    source, timeline, d_manifest = load_e_inputs(db_path, projects_root, project_id)
    payload = valid_e_payload(timeline)
    payload["forbidden_claims"] = ["real name and nickname inference prohibited"]
    script = EScript.model_validate(payload)

    with pytest.raises(EScriptValidationError):
        validate_e_script_against_inputs(
            script,
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
        )


def test_overlong_narration_for_scene_duration_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    source, timeline, d_manifest = load_e_inputs(db_path, projects_root, project_id)
    payload = valid_e_payload(timeline)
    payload["narration_script"][0]["script"] = "x" * 250
    script = EScript.model_validate(payload)

    with pytest.raises(EScriptValidationError):
        validate_e_script_against_inputs(
            script,
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
        )


def test_forbidden_raw_source_fields_are_blocked_and_not_written(tmp_path) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)
    invalid_payload = valid_e_payload(timeline)
    invalid_payload["raw_html"] = "<html>secret</html>"
    provider = SequenceEProvider([invalid_payload])

    with pytest.raises(EScriptGenerationError):
        generate_e_script(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            provider=provider,
            clock=fixed_clock,
            max_retries=0,
        )

    assert not e_path(projects_root, project_id).exists()
    assert fetch_count(db_path, "scripts") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type = 'e_script'") == 0


def test_wrong_status_is_blocked_without_e_side_effects(tmp_path) -> None:
    db_path, projects_root, project_id = create_selected_project(tmp_path)
    payload = valid_e_payload(
        TimelineJson(
            project_id=project_id,
            canvas={"duration_target_sec": 34},
            source={
                "source_url": "https://example.com/community/post/123",
                "source_community": "manual",
                "source_title": "Manual source candidate",
                "user_or_llm_summary": "Safe summary.",
                "hook": "Safe hook.",
                "why_shortable": "Safe reason.",
                "risk_flags_for_user": [],
            },
            style=valid_b_payload()["selected_style"],
            total_duration_sec=34,
            scenes=[
                {
                    "scene_id": f"s{index:02d}",
                    "start_sec": start,
                    "duration_sec": duration,
                    "screen_text": f"scene {index}",
                    "image_slot_id": f"slot_{index:03d}",
                    "image_slot_description": "safe image",
                    "narration_intent": "safe narration",
                    "bgm_instruction": None,
                    "transition": "cut",
                    "fact_basis": ["safe basis"],
                    "avoid_claims": ["avoid unsafe claims"],
                    "image_path": f"assets/user_images/slot_{index:03d}.png",
                    "text_overlay_path": f"assets/text_overlays/s{index:02d}_text.png",
                }
                for index, start, duration in [
                    (1, 0.0, 8.0),
                    (2, 8.0, 9.0),
                    (3, 17.0, 9.0),
                    (4, 26.0, 8.0),
                ]
            ],
        )
    )

    with pytest.raises(ProjectStatusError):
        generate_e_script(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            provider=SequenceEProvider([payload]),
            clock=fixed_clock,
        )

    assert not e_path(projects_root, project_id).exists()
    assert fetch_count(db_path, "scripts") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type = 'e_script'") == 0
    assert project_status(db_path, project_id) == "candidate_selected"


def test_file_write_failure_rolls_back_e_db_state(tmp_path, monkeypatch) -> None:
    db_path, projects_root, project_id, timeline, _manifest = create_ready_project(tmp_path)

    def fail_write(*args, **kwargs):
        raise OSError("simulated E write failure")

    monkeypatch.setattr("shorts_pipeline.e_service.write_e_script_json", fail_write)

    with pytest.raises(OSError):
        generate_e_script(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            provider=SequenceEProvider([valid_e_payload(timeline)]),
            clock=fixed_clock,
        )

    assert not e_path(projects_root, project_id).exists()
    assert fetch_count(db_path, "scripts") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type = 'e_script'") == 0
    assert project_status(db_path, project_id) == "images_inserted"
