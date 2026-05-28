from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import ValidationError

from shorts_pipeline.b_service import generate_b_scene_plan
from shorts_pipeline.c_service import (
    CCompilerInputError,
    ProjectStatusError,
    TimelineValidationError,
    compile_c_project,
    validate_timeline_against_b_plan,
)
from shorts_pipeline.db import connect_db
from shorts_pipeline.models import BScenePlan, SourceArtifact, TimelineJson
from shorts_pipeline.project_service import create_project_from_candidate
from shorts_pipeline.projectgen.timeline import build_timeline_from_b_plan
from shorts_pipeline.security import sha256_file

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

    def generate(
        self,
        *,
        source: SourceArtifact,
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        return copy.deepcopy(valid_b_payload())


def create_project(tmp_path) -> tuple[Path, Path, str]:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    project = create_project_from_candidate(
        load_candidate(),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    return db_path, projects_root, project.project_id


def create_planned_project(tmp_path) -> tuple[Path, Path, str]:
    db_path, projects_root, project_id = create_project(tmp_path)
    generate_b_scene_plan(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=StaticBProvider(),
        clock=fixed_clock,
    )
    return db_path, projects_root, project_id


def fetch_one(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row:
    conn = connect_db(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def fetch_all(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn = connect_db(db_path)
    try:
        return conn.execute(sql, params).fetchall()
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


def b_plan_from_project(projects_root: Path, project_id: str) -> BScenePlan:
    data = json.loads((projects_root / project_id / "b_scene_plan.json").read_text(encoding="utf-8"))
    return BScenePlan.model_validate(data)


def test_happy_path_compiles_timeline_files_db_and_status(tmp_path) -> None:
    db_path, projects_root, project_id = create_planned_project(tmp_path)

    timeline = compile_c_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    assert isinstance(timeline, TimelineJson)
    project_dir = projects_root / project_id
    timeline_path = project_dir / "timeline.json"
    assert timeline_path.is_file()
    reloaded = TimelineJson.model_validate(json.loads(timeline_path.read_text(encoding="utf-8")))
    assert reloaded.project_id == project_id
    assert project_status(db_path, project_id) == "project_generated"

    timeline_row = fetch_one(db_path, "SELECT * FROM timelines WHERE project_id = ?", (project_id,))
    assert timeline_row["schema_version"] == "timeline.v2.1"
    assert timeline_row["artifact_path"] == f"{project_id}/timeline.json"
    assert timeline_row["total_duration_sec"] == timeline.total_duration_sec
    assert json.loads(timeline_row["timeline_json"])["project_id"] == project_id

    artifact_rows = fetch_all(
        db_path,
        "SELECT * FROM artifacts WHERE project_id = ? AND artifact_type != ?",
        (project_id, "b_scene_plan"),
    )
    artifact_types = [row["artifact_type"] for row in artifact_rows]
    assert artifact_types.count("timeline") == 1
    assert artifact_types.count("placeholder_image") == len(timeline.scenes)
    assert artifact_types.count("user_image_slot") == len(timeline.scenes)
    assert artifact_types.count("text_overlay") == len(timeline.scenes)
    assert artifact_types.count("replace_images_guide") == 1

    for row in artifact_rows:
        relative_path = Path(row["relative_path"])
        assert not relative_path.is_absolute()
        assert ".." not in relative_path.parts
        actual_path = projects_root / row["relative_path"]
        assert actual_path.is_file()
        assert row["sha256"] == sha256_file(actual_path)


def test_timeline_start_times_are_cumulative_for_five_scene_payload(tmp_path) -> None:
    db_path, projects_root, project_id = create_project(tmp_path)
    payload = valid_b_payload()
    scene_five = copy.deepcopy(payload["scene_plan"][-1])
    scene_five["scene_id"] = "s05"
    payload["scene_plan"].append(scene_five)
    payload["target_duration_sec"] = 40
    for scene, duration in zip(payload["scene_plan"], [7.0, 9.0, 8.0, 8.0, 8.0], strict=True):
        scene["duration_sec"] = duration
    provider = StaticBProvider()
    provider.generate = lambda **_: copy.deepcopy(payload)
    generate_b_scene_plan(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=provider,
        clock=fixed_clock,
    )

    compile_c_project(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)

    timeline = TimelineJson.model_validate(
        json.loads((projects_root / project_id / "timeline.json").read_text(encoding="utf-8"))
    )
    assert [scene.start_sec for scene in timeline.scenes] == [0.0, 7.0, 16.0, 24.0, 32.0]
    assert timeline.total_duration_sec == 40.0


def test_placeholder_and_user_image_files_are_generated_and_match(tmp_path) -> None:
    db_path, projects_root, project_id = create_planned_project(tmp_path)
    timeline = compile_c_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    project_dir = projects_root / project_id

    for scene in timeline.scenes:
        placeholder = project_dir / "assets" / "placeholders" / f"{scene.image_slot_id}_placeholder.png"
        user_image = project_dir / scene.image_path
        assert placeholder.read_bytes() == user_image.read_bytes()
        for image_path in [placeholder, user_image]:
            with Image.open(image_path) as image:
                assert image.size == (1080, 1920)
                assert image.format == "PNG"


def test_text_overlay_png_files_are_generated_with_alpha(tmp_path) -> None:
    db_path, projects_root, project_id = create_planned_project(tmp_path)
    timeline = compile_c_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    project_dir = projects_root / project_id

    for scene in timeline.scenes:
        overlay_path = project_dir / scene.text_overlay_path
        with Image.open(overlay_path) as image:
            assert image.size == (1080, 1920)
            assert image.format == "PNG"
            assert image.mode == "RGBA"


def test_replace_images_guide_contains_required_warnings_and_slots(tmp_path) -> None:
    db_path, projects_root, project_id = create_planned_project(tmp_path)
    timeline = compile_c_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    guide = (projects_root / project_id / "notes" / "replace_images.md").read_text(encoding="utf-8")

    assert project_id in guide
    assert "original post screenshots" in guide
    assert "personal information" in guide
    assert "real names or nicknames" in guide
    assert "rights confirmation" in guide
    for scene in timeline.scenes:
        assert scene.scene_id in guide
        assert scene.image_slot_id in guide
        assert scene.image_path in guide


def test_wrong_status_is_blocked_without_c_side_effects(tmp_path) -> None:
    db_path, projects_root, project_id = create_project(tmp_path)

    with pytest.raises(ProjectStatusError):
        compile_c_project(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)

    assert project_status(db_path, project_id) == "candidate_selected"
    assert not (projects_root / project_id / "timeline.json").exists()
    assert not (projects_root / project_id / "assets" / "user_images" / "slot_001.png").exists()
    assert fetch_count(db_path, "timelines") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type != 'b_scene_plan'") == 0


def test_missing_b_scene_plan_is_blocked_without_c_side_effects(tmp_path) -> None:
    db_path, projects_root, project_id = create_project(tmp_path)
    conn = connect_db(db_path)
    try:
        conn.execute("UPDATE projects SET status = ? WHERE id = ?", ("planned", project_id))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(CCompilerInputError):
        compile_c_project(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)

    assert project_status(db_path, project_id) == "planned"
    assert not (projects_root / project_id / "timeline.json").exists()
    assert fetch_count(db_path, "timelines") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type != 'b_scene_plan'") == 0


def test_invalid_b_scene_plan_is_blocked_without_c_side_effects(tmp_path) -> None:
    db_path, projects_root, project_id = create_project(tmp_path)
    project_dir = projects_root / project_id
    (project_dir / "b_scene_plan.json").write_text('{"schema_version": "bad"}', encoding="utf-8")
    conn = connect_db(db_path)
    try:
        conn.execute("UPDATE projects SET status = ? WHERE id = ?", ("planned", project_id))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValidationError):
        compile_c_project(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)

    assert project_status(db_path, project_id) == "planned"
    assert not (project_dir / "timeline.json").exists()
    assert fetch_count(db_path, "timelines") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type != 'b_scene_plan'") == 0


def test_timeline_validator_catches_bad_start_times() -> None:
    source = SourceArtifact(
        project_id="PRJ_20260529_0001",
        source_url="https://example.com/community/post/123",
        source_community="example_community",
        source_title="Manual source candidate",
        user_or_llm_summary="A safe summary.",
        hook="A safe hook.",
        why_shortable="A safe reason.",
        risk_flags_for_user=[],
        created_at="2026-05-29T10:30:00+09:00",
    )
    b_plan = BScenePlan.model_validate(valid_b_payload())
    timeline = build_timeline_from_b_plan(b_plan, source=source, project_id=source.project_id)
    timeline.scenes[1].start_sec = 999

    with pytest.raises(TimelineValidationError):
        validate_timeline_against_b_plan(timeline, b_plan, source)


def test_timeline_validator_catches_unsafe_paths() -> None:
    source = source_from_project_for_validator()
    b_plan = BScenePlan.model_validate(valid_b_payload())
    timeline = build_timeline_from_b_plan(b_plan, source=source, project_id=source.project_id)

    for unsafe_path in ["../evil.png", "https://example.com/image.png", "/tmp/image.png"]:
        mutated = timeline.model_copy(deep=True)
        mutated.scenes[0].image_path = unsafe_path
        with pytest.raises((TimelineValidationError, ValueError)):
            validate_timeline_against_b_plan(mutated, b_plan, source)


def test_timeline_validator_catches_forbidden_source_keys() -> None:
    source = source_from_project_for_validator()
    b_plan = BScenePlan.model_validate(valid_b_payload())
    timeline = build_timeline_from_b_plan(b_plan, source=source, project_id=source.project_id)
    timeline.source["raw_html"] = "<html></html>"

    with pytest.raises(TimelineValidationError):
        validate_timeline_against_b_plan(timeline, b_plan, source)


def source_from_project_for_validator() -> SourceArtifact:
    return SourceArtifact(
        project_id="PRJ_20260529_0001",
        source_url="https://example.com/community/post/123",
        source_community="example_community",
        source_title="Manual source candidate",
        user_or_llm_summary="A safe summary.",
        hook="A safe hook.",
        why_shortable="A safe reason.",
        risk_flags_for_user=[],
        created_at="2026-05-29T10:30:00+09:00",
    )
