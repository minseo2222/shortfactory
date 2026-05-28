from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from shorts_pipeline.db import connect_db
from shorts_pipeline.models import SourceArtifact
from shorts_pipeline.project_service import (
    create_project_folder,
    create_project_from_candidate,
)
from shorts_pipeline.security import SecurityValidationError

FIXTURES = Path(__file__).parent / "fixtures"
FORBIDDEN_SOURCE_KEYS = {
    "full_text",
    "comments",
    "raw_html",
    "screenshot_path",
    "api_key",
    "secret",
}


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def load_candidate() -> dict:
    return json.loads((FIXTURES / "sample_source.json").read_text(encoding="utf-8"))


def read_project_rows(db_path: Path) -> list[sqlite3.Row]:
    conn = connect_db(db_path)
    try:
        return conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
    finally:
        conn.close()


def test_happy_path_creates_project_row_folder_and_required_files(tmp_path) -> None:
    db_path = tmp_path / "db" / "shorts.sqlite3"
    projects_root = tmp_path / "projects"

    project = create_project_from_candidate(
        load_candidate(),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    assert project.project_id == "PRJ_20260529_0001"
    assert project.status == "candidate_selected"

    rows = read_project_rows(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "PRJ_20260529_0001"
    assert row["status"] == "candidate_selected"
    assert row["project_dir"] == "PRJ_20260529_0001"

    project_dir = projects_root / project.project_id
    assert project_dir.is_dir()
    assert (project_dir / "source.json").is_file()
    for relative_path in [
        "assets/placeholders",
        "assets/user_images",
        "assets/text_overlays",
        "assets/bgm",
        "notes",
        "exports",
        "logs",
    ]:
        assert (project_dir / relative_path).is_dir()

    for relative_path in [
        "assets/bgm/README.md",
        "notes/replace_images.md",
        "notes/recording_guide.md",
        "notes/source_policy.md",
        "exports/README.md",
    ]:
        assert (project_dir / relative_path).is_file()


def test_source_json_validates_and_uses_safe_storage_policy(tmp_path) -> None:
    project = create_project_from_candidate(
        load_candidate(),
        db_path=tmp_path / "shorts.sqlite3",
        projects_root=tmp_path / "projects",
        clock=fixed_clock,
    )

    source_data = json.loads(Path(project.source_json_path).read_text(encoding="utf-8"))
    source = SourceArtifact.model_validate(source_data)

    assert source.schema_version == "source.v2.1"
    assert source.project_id == "PRJ_20260529_0001"
    assert source.storage_policy.full_source_post_stored is False
    assert source.storage_policy.full_comments_stored is False
    assert source.storage_policy.original_screenshot_stored is False


def test_source_json_contains_no_forbidden_storage_fields(tmp_path) -> None:
    project = create_project_from_candidate(
        load_candidate(),
        db_path=tmp_path / "shorts.sqlite3",
        projects_root=tmp_path / "projects",
        clock=fixed_clock,
    )
    source_data = json.loads(Path(project.source_json_path).read_text(encoding="utf-8"))

    assert FORBIDDEN_SOURCE_KEYS.isdisjoint(source_data)


def test_project_id_sequence_increments_for_same_clock_date(tmp_path) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"

    first = create_project_from_candidate(
        load_candidate(),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    second_candidate = load_candidate()
    second_candidate["candidate_id"] = "cand_002"
    second_candidate["source_url"] = "https://example.com/community/post/456"
    second = create_project_from_candidate(
        second_candidate,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    assert first.project_id == "PRJ_20260529_0001"
    assert second.project_id == "PRJ_20260529_0002"
    assert [row["id"] for row in read_project_rows(db_path)] == [
        "PRJ_20260529_0001",
        "PRJ_20260529_0002",
    ]


def test_invalid_candidate_fails_before_project_creation(tmp_path) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    candidate = load_candidate()
    candidate["title"] = ""
    candidate["summary"] = ""

    with pytest.raises(ValidationError):
        create_project_from_candidate(
            candidate,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert not db_path.exists()
    assert not projects_root.exists()


def test_path_safety_rejects_project_id_escape_attempt(tmp_path) -> None:
    with pytest.raises(SecurityValidationError):
        create_project_folder(tmp_path / "projects", "../evil")


def test_db_row_project_dir_points_to_existing_project_directory(tmp_path) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    create_project_from_candidate(
        load_candidate(),
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    row = read_project_rows(db_path)[0]
    assert (projects_root / row["project_dir"]).is_dir()


def test_source_write_failure_rolls_back_db_row_and_folder(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"

    def fail_write_source_json(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(
        "shorts_pipeline.project_service.write_source_json",
        fail_write_source_json,
    )

    with pytest.raises(OSError):
        create_project_from_candidate(
            load_candidate(),
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert read_project_rows(db_path) == []
    assert not (projects_root / "PRJ_20260529_0001").exists()
