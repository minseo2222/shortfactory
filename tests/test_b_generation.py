from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from shorts_pipeline.b_service import (
    BScenePlanGenerationError,
    BScenePlanValidationError,
    ProviderNotConfiguredError,
    generate_b_scene_plan,
    validate_b_scene_plan_against_source,
)
from shorts_pipeline.db import connect_db
from shorts_pipeline.models import BScenePlan, SourceArtifact
from shorts_pipeline.project_service import create_project_from_candidate
from shorts_pipeline.security import sha256_file

FIXTURES = Path(__file__).parent / "fixtures"
FORBIDDEN_B_TERMS = {
    "full_text",
    "comments",
    "raw_html",
    "screenshot",
    "api_key",
    "secret",
}


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def load_candidate() -> dict[str, Any]:
    return json.loads((FIXTURES / "sample_source.json").read_text(encoding="utf-8"))


def valid_b_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "sample_b_scene_plan.json").read_text(encoding="utf-8"))


def source_artifact() -> SourceArtifact:
    return SourceArtifact(
        project_id="PRJ_20260529_0001",
        source_url="https://example.com/community/post/123",
        source_community="manual",
        source_title="A title with copied phrase inside",
        user_or_llm_summary="A summary that should only be used as source metadata.",
        hook="A small decision creates a larger conflict.",
        why_shortable="The situation has a clear setup and reversal.",
        risk_flags_for_user=[],
        created_at="2026-05-29T10:30:00+09:00",
    )


class SequenceBProvider:
    provider_name = "fake"
    model_name = "mock-b-scene-plan-v2.1"

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.call_count = 0
        self.previous_errors_by_call: list[list[str]] = []

    def generate(
        self,
        *,
        source: SourceArtifact,
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        self.call_count += 1
        self.previous_errors_by_call.append(list(previous_errors))
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


def fetch_one(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row:
    conn = connect_db(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def fetch_count(db_path: Path, table: str) -> int:
    conn = connect_db(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def project_status(db_path: Path, project_id: str) -> str:
    return fetch_one(db_path, "SELECT status FROM projects WHERE id = ?", (project_id,))["status"]


def test_happy_path_persists_b_plan_artifact_and_status(tmp_path) -> None:
    db_path, projects_root, project_id = create_selected_project(tmp_path)
    provider = SequenceBProvider([valid_b_payload()])

    plan = generate_b_scene_plan(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=provider,
        clock=fixed_clock,
    )

    assert isinstance(plan, BScenePlan)
    b_path = projects_root / project_id / "b_scene_plan.json"
    assert b_path.is_file()
    reloaded = BScenePlan.model_validate(json.loads(b_path.read_text(encoding="utf-8")))
    assert reloaded.schema_version == "b_scene_plan.v2.1"
    serialized = json.dumps(reloaded.model_dump(mode="json")).casefold()
    assert all(term not in serialized for term in FORBIDDEN_B_TERMS)

    assert project_status(db_path, project_id) == "planned"

    plan_row = fetch_one(db_path, "SELECT * FROM plans WHERE project_id = ?", (project_id,))
    assert plan_row["schema_version"] == "b_scene_plan.v2.1"
    assert plan_row["artifact_path"] == f"{project_id}/b_scene_plan.json"
    assert json.loads(plan_row["scene_plan_json"])["schema_version"] == "b_scene_plan.v2.1"
    assert plan_row["llm_run_id"] is not None

    artifact_row = fetch_one(
        db_path,
        "SELECT * FROM artifacts WHERE project_id = ? AND artifact_type = ?",
        (project_id, "b_scene_plan"),
    )
    assert artifact_row["relative_path"] == f"{project_id}/b_scene_plan.json"
    assert not Path(artifact_row["relative_path"]).is_absolute()
    assert ".." not in Path(artifact_row["relative_path"]).parts
    assert artifact_row["sha256"] == sha256_file(b_path)

    llm_row = fetch_one(db_path, "SELECT * FROM llm_runs WHERE project_id = ?", (project_id,))
    assert llm_row["stage"] == "B"
    assert llm_row["provider"] == "fake"
    assert llm_row["model_name"] == "mock-b-scene-plan-v2.1"
    assert llm_row["prompt_version"] == "b_scene_plan_prompt.v2.1.001"
    assert llm_row["schema_version"] == "b_scene_plan.v2.1"
    assert llm_row["status"] == "succeeded"


def test_retry_succeeds_after_invalid_first_response(tmp_path) -> None:
    db_path, projects_root, project_id = create_selected_project(tmp_path)
    invalid_payload = valid_b_payload()
    invalid_payload["scene_plan"][0]["do_not_say"] = []
    provider = SequenceBProvider([invalid_payload, valid_b_payload()])

    generate_b_scene_plan(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=provider,
        clock=fixed_clock,
    )

    assert provider.call_count == 2
    assert provider.previous_errors_by_call[0] == []
    assert provider.previous_errors_by_call[1]
    assert (projects_root / project_id / "b_scene_plan.json").is_file()
    assert fetch_count(db_path, "plans") == 1
    assert fetch_count(db_path, "artifacts") == 1
    assert project_status(db_path, project_id) == "planned"


def test_retry_exhaustion_leaves_no_b_state(tmp_path) -> None:
    db_path, projects_root, project_id = create_selected_project(tmp_path)
    invalid_payload = valid_b_payload()
    invalid_payload["scene_plan"][0]["do_not_say"] = []
    provider = SequenceBProvider([invalid_payload])

    with pytest.raises(BScenePlanGenerationError):
        generate_b_scene_plan(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            provider=provider,
            clock=fixed_clock,
            max_retries=2,
        )

    assert provider.call_count == 3
    assert not (projects_root / project_id / "b_scene_plan.json").exists()
    assert fetch_count(db_path, "plans") == 0
    assert fetch_count(db_path, "artifacts") == 0
    assert project_status(db_path, project_id) == "candidate_selected"


def test_app_validator_rejects_nonconsecutive_scene_ids() -> None:
    payload = valid_b_payload()
    payload["scene_plan"][1]["scene_id"] = "s03"
    plan = BScenePlan.model_validate(payload)

    with pytest.raises(BScenePlanValidationError):
        validate_b_scene_plan_against_source(plan, source_artifact())


def test_app_validator_rejects_duration_outside_target_window() -> None:
    payload = valid_b_payload()
    payload["target_duration_sec"] = 45
    for scene in payload["scene_plan"]:
        scene["duration_sec"] = 5
    plan = BScenePlan.model_validate(payload)

    with pytest.raises(BScenePlanValidationError):
        validate_b_scene_plan_against_source(plan, source_artifact())


def test_app_validator_rejects_direct_copy_screen_text() -> None:
    payload = valid_b_payload()
    payload["scene_plan"][0]["screen_text"] = "copied phrase"
    plan = BScenePlan.model_validate(payload)

    with pytest.raises(BScenePlanValidationError):
        validate_b_scene_plan_against_source(plan, source_artifact())


def test_app_validator_rejects_missing_safety_guard() -> None:
    payload = valid_b_payload()
    payload["scene_plan"][0]["do_not_say"] = []
    plan = BScenePlan.model_validate(payload)

    with pytest.raises(BScenePlanValidationError):
        validate_b_scene_plan_against_source(plan, source_artifact())


def test_no_provider_means_no_network_fallback_or_status_change(tmp_path) -> None:
    db_path, projects_root, project_id = create_selected_project(tmp_path)

    with pytest.raises(ProviderNotConfiguredError):
        generate_b_scene_plan(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            provider=None,
            clock=fixed_clock,
        )

    assert not (projects_root / project_id / "b_scene_plan.json").exists()
    assert fetch_count(db_path, "plans") == 0
    assert fetch_count(db_path, "artifacts") == 0
    assert project_status(db_path, project_id) == "candidate_selected"
