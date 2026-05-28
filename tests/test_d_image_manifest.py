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
from shorts_pipeline.c_service import compile_c_project
from shorts_pipeline.d_service import (
    DImageManifestInputError,
    DImageManifestValidationError,
    ProjectStatusError,
    assert_d_image_manifest_ready_for_e,
    confirm_d_image_manifest,
    initialize_d_image_manifest,
)
from shorts_pipeline.db import connect_db
from shorts_pipeline.models import DImageManifest, SourceArtifact, TimelineJson
from shorts_pipeline.project_service import create_project_from_candidate
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


def create_generated_project(tmp_path) -> tuple[Path, Path, str, TimelineJson]:
    db_path, projects_root, project_id = create_project(tmp_path)
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
                "actual_image_note": f"User-owned safe image for {scene.scene_id}.",
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


def manifest_path(projects_root: Path, project_id: str) -> Path:
    return projects_root / project_id / "d_image_manifest.json"


def test_draft_initialization_happy_path(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)

    manifest = initialize_d_image_manifest(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    path = manifest_path(projects_root, project_id)
    assert isinstance(manifest, DImageManifest)
    assert path.is_file()
    reloaded = DImageManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert len(reloaded.slots) == len(timeline.scenes)
    assert reloaded.image_insert_completed is False
    assert reloaded.user_confirmed is False
    assert project_status(db_path, project_id) == "waiting_for_user_images"

    for slot, scene in zip(reloaded.slots, timeline.scenes, strict=True):
        assert slot.status == "placeholder"
        assert slot.slot_id == scene.image_slot_id
        assert slot.scene_id == scene.scene_id
        assert slot.planned_image_path == scene.image_path
        assert slot.actual_image_path == scene.image_path
        assert slot.source_type == "app_generated_placeholder"
        assert slot.rights_confirmed_by_user is False
        assert slot.image_sha256 == sha256_file(projects_root / project_id / scene.image_path)

    artifact = fetch_one(
        db_path,
        "SELECT * FROM artifacts WHERE project_id = ? AND artifact_type = ?",
        (project_id, "d_image_manifest"),
    )
    assert artifact["relative_path"] == f"{project_id}/d_image_manifest.json"
    assert not Path(artifact["relative_path"]).is_absolute()
    assert ".." not in Path(artifact["relative_path"]).parts
    assert artifact["sha256"] == sha256_file(path)


def test_confirmation_happy_path_with_replaced_images(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    payload = ready_payload_from_timeline(timeline)

    manifest = confirm_d_image_manifest(
        project_id,
        payload,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    assert project_status(db_path, project_id) == "images_inserted"
    assert manifest.completed_at is not None
    for slot in manifest.slots:
        actual_path = projects_root / project_id / slot.actual_image_path
        assert slot.image_sha256 == sha256_file(actual_path)
        with Image.open(actual_path) as image:
            assert image.format == "PNG"
            assert image.size == (1080, 1920)

    assert fetch_count(db_path, "image_manifests") == 1
    assert fetch_count(db_path, "artifacts", "artifact_type = 'd_image_manifest'") == 1


def test_direct_confirmation_from_project_generated(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)

    confirm_d_image_manifest(
        project_id,
        ready_payload_from_timeline(timeline),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    assert project_status(db_path, project_id) == "images_inserted"
    assert manifest_path(projects_root, project_id).is_file()
    assert fetch_count(db_path, "image_manifests") == 1


def test_e_readiness_helper_happy_path(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    confirm_d_image_manifest(
        project_id,
        ready_payload_from_timeline(timeline),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    manifest = assert_d_image_manifest_ready_for_e(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
    )

    assert isinstance(manifest, DImageManifest)
    assert manifest.image_insert_completed is True


def test_wrong_status_is_blocked_without_d_side_effects(tmp_path) -> None:
    db_path, projects_root, project_id = create_project(tmp_path)

    with pytest.raises(ProjectStatusError):
        initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)

    assert not manifest_path(projects_root, project_id).exists()
    assert fetch_count(db_path, "image_manifests") == 0
    assert fetch_count(db_path, "artifacts", "artifact_type = 'd_image_manifest'") == 0
    assert project_status(db_path, project_id) == "candidate_selected"


def test_missing_timeline_is_blocked_without_d_side_effects(tmp_path) -> None:
    db_path, projects_root, project_id = create_project(tmp_path)
    conn = connect_db(db_path)
    try:
        conn.execute("UPDATE projects SET status = ? WHERE id = ?", ("project_generated", project_id))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(DImageManifestInputError):
        initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)

    assert not manifest_path(projects_root, project_id).exists()
    assert fetch_count(db_path, "image_manifests") == 0
    assert project_status(db_path, project_id) == "project_generated"


def test_slot_mismatch_is_blocked_without_overwriting_existing_manifest(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    before = manifest_path(projects_root, project_id).read_text(encoding="utf-8")
    payload = ready_payload_from_timeline(timeline)
    payload["slots"][0]["slot_id"] = "slot_999"

    with pytest.raises(DImageManifestValidationError):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert manifest_path(projects_root, project_id).read_text(encoding="utf-8") == before
    assert project_status(db_path, project_id) == "waiting_for_user_images"


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../evil.png",
        "/tmp/image.png",
        "https://example.com/image.png",
        "assets/user_images/../../evil.png",
    ],
)
def test_unsafe_actual_image_path_is_blocked(tmp_path, unsafe_path: str) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    payload = ready_payload_from_timeline(timeline)
    payload["slots"][0]["actual_image_path"] = unsafe_path

    with pytest.raises((ValidationError, DImageManifestValidationError)):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert project_status(db_path, project_id) == "waiting_for_user_images"


def test_missing_actual_image_file_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    payload = ready_payload_from_timeline(timeline)
    payload["slots"][0]["actual_image_path"] = "assets/user_images/missing.png"

    with pytest.raises(DImageManifestValidationError):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert project_status(db_path, project_id) == "waiting_for_user_images"


def test_non_png_or_wrong_dimension_image_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    bad_path = projects_root / project_id / timeline.scenes[0].image_path
    Image.new("RGB", (64, 64), "#000000").save(bad_path)
    payload = ready_payload_from_timeline(timeline)

    with pytest.raises(DImageManifestValidationError):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert project_status(db_path, project_id) == "waiting_for_user_images"


def test_replaced_image_without_note_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    payload = ready_payload_from_timeline(timeline)
    payload["slots"][0]["actual_image_note"] = " "

    with pytest.raises(ValidationError):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert project_status(db_path, project_id) == "waiting_for_user_images"


@pytest.mark.parametrize(
    "field,value",
    [
        ("rights_confirmed_by_user", False),
        ("contains_personal_info", True),
        ("contains_original_capture", True),
        ("contains_community_logo", True),
    ],
)
def test_unsafe_ready_flags_are_blocked(tmp_path, field: str, value: bool) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    payload = ready_payload_from_timeline(timeline)
    payload["slots"][0][field] = value

    with pytest.raises(DImageManifestValidationError):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert project_status(db_path, project_id) == "waiting_for_user_images"


def test_face_without_face_rights_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    payload = ready_payload_from_timeline(timeline)
    payload["slots"][0]["contains_face"] = True
    payload["slots"][0]["face_rights_confirmed"] = False

    with pytest.raises(DImageManifestValidationError):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert project_status(db_path, project_id) == "waiting_for_user_images"


def test_hash_mismatch_is_blocked(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    payload = ready_payload_from_timeline(timeline)
    payload["slots"][0]["image_sha256"] = "0" * 64

    with pytest.raises(DImageManifestValidationError):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert project_status(db_path, project_id) == "waiting_for_user_images"


def test_extra_forbidden_field_is_blocked_and_not_written(tmp_path) -> None:
    db_path, projects_root, project_id, timeline = create_generated_project(tmp_path)
    initialize_d_image_manifest(project_id, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    before = manifest_path(projects_root, project_id).read_text(encoding="utf-8")
    payload = ready_payload_from_timeline(timeline)
    payload["raw_html"] = "<html>secret</html>"

    with pytest.raises(ValidationError):
        confirm_d_image_manifest(
            project_id,
            payload,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    after = manifest_path(projects_root, project_id).read_text(encoding="utf-8")
    assert after == before
    assert "raw_html" not in after
    assert project_status(db_path, project_id) == "waiting_for_user_images"
