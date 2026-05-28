from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, get_args

import pytest

from shorts_pipeline.db import connect_db, list_project_status_events
from shorts_pipeline.e_service import EScriptGenerationError
from shorts_pipeline.models import (
    BScenePlan,
    DImageManifest,
    EScript,
    NarrationPace,
    SmokeRunResult,
    SourceArtifact,
    TimelineJson,
    TitleAngle,
)
from shorts_pipeline.security import ensure_relative_project_path, sha256_file
from shorts_pipeline.smoke import (
    EXPECTED_STATUS_SEQUENCE,
    SmokeProviderNotConfiguredError,
    run_local_smoke_pipeline,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def valid_b_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "sample_b_scene_plan.json").read_text(encoding="utf-8"))


class FakeBProvider:
    provider_name = "fake"
    model_name = "mock-b-scene-plan-v2.1"

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or valid_b_payload()
        self.call_count = 0

    def generate(
        self,
        *,
        source: SourceArtifact,
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        self.call_count += 1
        return copy.deepcopy(self.payload)


class FakeEProvider:
    provider_name = "fake"
    model_name = "mock-e-script-v2.1"

    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.call_count = 0
        self.contexts: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        context: dict[str, Any],
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        self.call_count += 1
        self.contexts.append(copy.deepcopy(context))
        timeline = TimelineJson.model_validate(context["timeline_json"])
        paces = list(get_args(NarrationPace))
        angles = list(get_args(TitleAngle))
        payload = {
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
                    "recording_note": "Record manually in a neutral tone.",
                    "fact_basis": [scene.fact_basis[0]],
                }
                for index, scene in enumerate(timeline.scenes)
            ],
            "title_candidates": [
                {
                    "title": "Why the small tip drew attention",
                    "angle": angles[0],
                    "fact_safety_note": "No identity or legal claim is added.",
                },
                {
                    "title": "The debate point stayed simple",
                    "angle": angles[1],
                    "fact_safety_note": "Only safe summary context is used.",
                },
                {
                    "title": "A cautious read of the reaction",
                    "angle": angles[2],
                    "fact_safety_note": "No raw replies are quoted.",
                },
                {
                    "title": "The safe takeaway from the discussion",
                    "angle": angles[3],
                    "fact_safety_note": "No unsupported facts are added.",
                },
                {
                    "title": "The reaction without source quotes",
                    "angle": angles[4],
                    "fact_safety_note": "No source quotation is reused.",
                },
            ],
            "recommended_title": "Why the small tip drew attention",
            "forbidden_claims": [
                "real name and nickname inference prohibited",
                "personal information prohibited",
                "crime assertion prohibited",
                "fabricated number prohibited",
                "direct quote from source prohibited",
                "original screenshot reuse prohibited",
            ],
        }
        if self.invalid:
            payload["recommended_title"] = "Not a candidate"
        return payload


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


def run_smoke(tmp_path) -> tuple[Path, Path, FakeBProvider, FakeEProvider, SmokeRunResult]:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    b_provider = FakeBProvider()
    e_provider = FakeEProvider()
    result = run_local_smoke_pipeline(
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
        b_provider=b_provider,
        e_provider=e_provider,
    )
    return db_path, projects_root, b_provider, e_provider, result


def test_end_to_end_smoke_happy_path(tmp_path) -> None:
    db_path, projects_root, b_provider, e_provider, result = run_smoke(tmp_path)

    SmokeRunResult.model_validate(result.model_dump(mode="json"))
    assert result.project_id == "PRJ_20260529_0001"
    assert result.final_status == "script_generated"
    assert result.status_sequence == EXPECTED_STATUS_SEQUENCE
    assert b_provider.call_count == 1
    assert e_provider.call_count == 1

    project_dir = projects_root / result.project_id
    source = SourceArtifact.model_validate(
        json.loads((project_dir / "source.json").read_text(encoding="utf-8"))
    )
    b_plan = BScenePlan.model_validate(
        json.loads((project_dir / "b_scene_plan.json").read_text(encoding="utf-8"))
    )
    timeline = TimelineJson.model_validate(
        json.loads((project_dir / "timeline.json").read_text(encoding="utf-8"))
    )
    manifest = DImageManifest.model_validate(
        json.loads((project_dir / "d_image_manifest.json").read_text(encoding="utf-8"))
    )
    script = EScript.model_validate(
        json.loads((project_dir / "e_script.json").read_text(encoding="utf-8"))
    )

    assert source.storage_policy.full_source_post_stored is False
    assert len(b_plan.scene_plan) == len(timeline.scenes)
    assert manifest.image_insert_completed is True
    assert script.recommended_title in {title.title for title in script.title_candidates}

    required_paths = {
        "source.json",
        "b_scene_plan.json",
        "timeline.json",
        "d_image_manifest.json",
        "e_script.json",
        "notes/replace_images.md",
        "assets/bgm/README.md",
        "exports/README.md",
    }
    for relative_path in required_paths:
        assert (project_dir / relative_path).is_file()

    for scene in timeline.scenes:
        assert (project_dir / "assets" / "placeholders" / f"{scene.image_slot_id}_placeholder.png").is_file()
        assert (project_dir / scene.image_path).is_file()
        assert (project_dir / scene.text_overlay_path).is_file()

    row = fetch_one(db_path, "SELECT status FROM projects WHERE id = ?", (result.project_id,))
    assert row["status"] == "script_generated"
    assert result.db_table_counts["projects"] == 1
    assert result.db_table_counts["plans"] == 1
    assert result.db_table_counts["timelines"] == 1
    assert result.db_table_counts["image_manifests"] == 1
    assert result.db_table_counts["scripts"] == 1
    assert result.db_table_counts["llm_runs"] == 2


def test_status_history_is_persisted(tmp_path) -> None:
    db_path, _projects_root, _b_provider, _e_provider, result = run_smoke(tmp_path)

    events = list_project_status_events(db_path, result.project_id)
    assert [event.to_status for event in events] == EXPECTED_STATUS_SEQUENCE
    assert [event.stage for event in events] == ["A", "B", "C", "D", "D", "E"]
    assert events[0].from_status is None
    for event in events[1:]:
        assert event.from_status
        assert event.project_id == result.project_id
        assert event.to_status
        assert event.reason
        assert event.created_at is not None


def test_artifact_set_completeness_and_db_hashes(tmp_path) -> None:
    db_path, projects_root, _b_provider, _e_provider, result = run_smoke(tmp_path)

    for check in result.artifact_checks:
        relative_path = ensure_relative_project_path(check.relative_path)
        path = projects_root / result.project_id / relative_path
        assert check.exists is True
        assert path.is_file()
        assert check.sha256 == sha256_file(path)

    artifact_rows = fetch_all(
        db_path,
        "SELECT artifact_type, relative_path, sha256 FROM artifacts WHERE project_id = ?",
        (result.project_id,),
    )
    artifact_types = [row["artifact_type"] for row in artifact_rows]
    for artifact_type in ["b_scene_plan", "timeline", "d_image_manifest", "e_script"]:
        assert artifact_type in artifact_types

    for row in artifact_rows:
        relative_path = ensure_relative_project_path(row["relative_path"])
        assert not Path(row["relative_path"]).is_absolute()
        assert ".." not in relative_path.parts
        actual_path = projects_root / relative_path
        assert actual_path.is_file()
        assert row["sha256"] == sha256_file(actual_path)


def test_provider_injection_is_required(tmp_path) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"

    with pytest.raises(SmokeProviderNotConfiguredError):
        run_local_smoke_pipeline(
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
            b_provider=None,
            e_provider=FakeEProvider(),
        )

    assert not db_path.exists()
    assert not projects_root.exists()


def test_d_confirmation_uses_local_generated_images_only(tmp_path) -> None:
    _db_path, projects_root, _b_provider, _e_provider, result = run_smoke(tmp_path)
    manifest = DImageManifest.model_validate(
        json.loads(
            (projects_root / result.project_id / "d_image_manifest.json").read_text(
                encoding="utf-8"
            )
        )
    )

    for slot in manifest.slots:
        assert slot.actual_image_path == f"assets/user_images/{slot.slot_id}.png"
        assert slot.source_type == "app_generated_placeholder"
        assert slot.rights_confirmed_by_user is True
        assert slot.contains_personal_info is False
        assert slot.contains_original_capture is False
        assert slot.contains_community_logo is False
        assert slot.image_sha256 == sha256_file(
            projects_root / result.project_id / slot.actual_image_path
        )
        assert "://" not in slot.actual_image_path
        assert "screenshot" not in (slot.actual_image_note or "").casefold()


def test_smoke_failure_does_not_fake_success(tmp_path) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"

    with pytest.raises(EScriptGenerationError):
        run_local_smoke_pipeline(
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
            b_provider=FakeBProvider(),
            e_provider=FakeEProvider(invalid=True),
        )

    project_id = "PRJ_20260529_0001"
    row = fetch_one(db_path, "SELECT status FROM projects WHERE id = ?", (project_id,))
    assert row["status"] == "images_inserted"
    assert not (projects_root / project_id / "e_script.json").exists()
    assert fetch_all(
        db_path,
        "SELECT * FROM artifacts WHERE project_id = ? AND artifact_type = ?",
        (project_id, "e_script"),
    ) == []
