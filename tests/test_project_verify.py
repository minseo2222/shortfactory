from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from shorts_pipeline.db import connect_db
from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider
from shorts_pipeline.models import ProjectFolderVerificationResult
from shorts_pipeline.project_verify import (
    ProjectNotFoundError,
    verify_generated_project_folder,
)
from shorts_pipeline.security import sha256_file
from shorts_pipeline.smoke import run_local_smoke_pipeline


TABLES_WITH_PROJECT_ID = [
    "plans",
    "timelines",
    "image_manifests",
    "scripts",
    "artifacts",
    "llm_runs",
    "project_status_events",
    "events",
]


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def run_smoke_project(tmp_path: Path, *, run_f: bool = False) -> tuple[Path, Path, str]:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    result = run_local_smoke_pipeline(
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
        b_provider=DevFakeBProvider(),
        e_provider=DevFakeEProvider(),
        run_f=run_f,
    )
    return db_path, projects_root, result.project_id


def project_dir(projects_root: Path, project_id: str) -> Path:
    return projects_root / project_id


def db_counts(db_path: Path, project_id: str) -> dict[str, int]:
    conn = connect_db(db_path)
    try:
        counts = {
            "projects": conn.execute(
                "SELECT COUNT(*) FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()[0]
        }
        for table in TABLES_WITH_PROJECT_ID:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
        return counts
    finally:
        conn.close()


def project_status(db_path: Path, project_id: str) -> str:
    conn = connect_db(db_path)
    try:
        row = conn.execute("SELECT status FROM projects WHERE id = ?", (project_id,)).fetchone()
        assert row is not None
        return row["status"]
    finally:
        conn.close()


def file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def assert_read_only_unchanged(
    *,
    db_path: Path,
    projects_root: Path,
    project_id: str,
    before_counts: dict[str, int],
    before_status: str,
    before_files: dict[str, str],
) -> None:
    assert db_counts(db_path, project_id) == before_counts
    assert project_status(db_path, project_id) == before_status
    assert file_snapshot(projects_root / project_id) == before_files


def artifact_rows_by_type(db_path: Path, project_id: str) -> dict[str, int]:
    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT artifact_type, COUNT(*) AS count
            FROM artifacts
            WHERE project_id = ?
            GROUP BY artifact_type
            """,
            (project_id,),
        ).fetchall()
        return {row["artifact_type"]: row["count"] for row in rows}
    finally:
        conn.close()


def insert_unsafe_artifact_row(db_path: Path, project_id: str, relative_path: str) -> None:
    conn = connect_db(db_path)
    try:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(
            """
            INSERT INTO artifacts (
                project_id,
                artifact_type,
                relative_path,
                sha256,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_id,
                "unsafe_test",
                relative_path,
                "0" * 64,
                "2026-05-29T10:30:00+09:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_verifier_happy_path_a_to_e_only_is_read_only(tmp_path) -> None:
    db_path, projects_root, project_id = run_smoke_project(tmp_path)
    before_counts = db_counts(db_path, project_id)
    before_status = project_status(db_path, project_id)
    before_files = file_snapshot(project_dir(projects_root, project_id))

    result = verify_generated_project_folder(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
    )

    ProjectFolderVerificationResult.model_validate(result.model_dump(mode="json"))
    assert result.schema_version == "project_folder_verification.v2.1"
    assert result.project_id == project_id
    assert result.project_status == "script_generated"
    assert result.require_f is False
    assert result.verified_a_to_e is True
    assert result.verified_f is False
    assert result.problem_count == 0
    item_names = {item.name for item in result.items}
    assert {
        "source.json",
        "b_scene_plan.json",
        "timeline.json",
        "d_image_manifest.json",
        "e_script.json",
    }.issubset(item_names)
    assert_read_only_unchanged(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        before_counts=before_counts,
        before_status=before_status,
        before_files=before_files,
    )


def test_verifier_happy_path_with_required_f_is_read_only(tmp_path) -> None:
    db_path, projects_root, project_id = run_smoke_project(tmp_path, run_f=True)
    before_counts = db_counts(db_path, project_id)
    before_status = project_status(db_path, project_id)
    before_files = file_snapshot(project_dir(projects_root, project_id))

    result = verify_generated_project_folder(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        require_f=True,
    )

    assert result.verified_a_to_e is True
    assert result.verified_f is True
    assert result.problem_count == 0
    assert any(item.name == "project.kdenlive_xml" and item.valid for item in result.items)
    assert {
        "kdenlive_project",
        "f_kdenlive_manifest",
        "manual_kdenlive_editing_guide",
    }.issubset(artifact_rows_by_type(db_path, project_id))
    assert_read_only_unchanged(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        before_counts=before_counts,
        before_status=before_status,
        before_files=before_files,
    )


def test_missing_f_artifact_is_reported_when_required_without_mutation(tmp_path) -> None:
    db_path, projects_root, project_id = run_smoke_project(tmp_path, run_f=True)
    (project_dir(projects_root, project_id) / "project.kdenlive").unlink()
    before_counts = db_counts(db_path, project_id)
    before_status = project_status(db_path, project_id)
    before_files = file_snapshot(project_dir(projects_root, project_id))

    result = verify_generated_project_folder(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        require_f=True,
    )

    assert result.problem_count > 0
    assert result.verified_f is False
    assert any(
        item.relative_path == "project.kdenlive" and item.problem
        for item in result.items
    )
    assert_read_only_unchanged(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        before_counts=before_counts,
        before_status=before_status,
        before_files=before_files,
    )


def test_f_artifacts_are_optional_when_not_required(tmp_path) -> None:
    db_path, projects_root, project_id = run_smoke_project(tmp_path)

    result_without_f = verify_generated_project_folder(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        require_f=False,
    )

    assert result_without_f.problem_count == 0
    assert result_without_f.verified_f is False

    f_db_path, f_projects_root, f_project_id = run_smoke_project(
        tmp_path / "with-f",
        run_f=True,
    )
    result_with_f_optional = verify_generated_project_folder(
        db_path=f_db_path,
        projects_root=f_projects_root,
        project_id=f_project_id,
        require_f=False,
    )

    assert result_with_f_optional.problem_count == 0
    optional_f_items = [
        item for item in result_with_f_optional.items if item.kind == "optional_f_artifact"
    ]
    assert optional_f_items
    assert all(item.required is False for item in optional_f_items)


def test_hash_mismatch_is_reported_without_repair(tmp_path) -> None:
    db_path, projects_root, project_id = run_smoke_project(tmp_path, run_f=True)
    manifest_path = project_dir(projects_root, project_id) / "f_kdenlive_manifest.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    before_counts = db_counts(db_path, project_id)
    before_status = project_status(db_path, project_id)
    before_files = file_snapshot(project_dir(projects_root, project_id))

    result = verify_generated_project_folder(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        require_f=True,
    )

    assert result.problem_count > 0
    assert any(
        item.relative_path == f"{project_id}/f_kdenlive_manifest.json"
        and item.sha256_matches is False
        for item in result.items
    )
    assert_read_only_unchanged(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        before_counts=before_counts,
        before_status=before_status,
        before_files=before_files,
    )


@pytest.mark.parametrize(
    "unsafe_path",
    ["../evil.txt", "/tmp/evil.txt", "https://example.com/evil.txt"],
)
def test_unsafe_artifact_path_is_reported_without_reading_outside_root(
    tmp_path,
    unsafe_path: str,
) -> None:
    db_path, projects_root, project_id = run_smoke_project(tmp_path, run_f=True)
    insert_unsafe_artifact_row(db_path, project_id, unsafe_path)
    before_counts = db_counts(db_path, project_id)
    before_status = project_status(db_path, project_id)
    before_files = file_snapshot(project_dir(projects_root, project_id))

    result = verify_generated_project_folder(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        require_f=True,
    )

    assert result.problem_count > 0
    unsafe_items = [
        item for item in result.items if item.name == "artifact_row:unsafe_test"
    ]
    assert unsafe_items
    assert unsafe_items[0].exists is None
    assert "unsafe artifact path" in (unsafe_items[0].problem or "")
    assert_read_only_unchanged(
        db_path=db_path,
        projects_root=projects_root,
        project_id=project_id,
        before_counts=before_counts,
        before_status=before_status,
        before_files=before_files,
    )


def test_unknown_project_id_raises_clear_error(tmp_path) -> None:
    db_path, projects_root, _project_id = run_smoke_project(tmp_path)

    with pytest.raises(ProjectNotFoundError, match="project not found"):
        verify_generated_project_folder(
            db_path=db_path,
            projects_root=projects_root,
            project_id="PRJ_20260529_9999",
        )
