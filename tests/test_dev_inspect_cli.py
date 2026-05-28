from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shorts_pipeline.dev_cli import main
from shorts_pipeline.db import connect_db

EXPECTED_SEQUENCE = [
    "candidate_selected",
    "planned",
    "project_generated",
    "waiting_for_user_images",
    "images_inserted",
    "script_generated",
]


def run_smoke_cli(tmp_path, capsys) -> tuple[Path, Path, str]:
    db_path = tmp_path / "db" / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    exit_code = main(
        [
            "smoke",
            "--db-path",
            str(db_path),
            "--projects-root",
            str(projects_root),
            "--use-fake-providers",
            "--fixed-clock",
            "2026-05-28T09:00:00+09:00",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    data = json.loads(captured.out)
    return db_path, projects_root, data["project_id"]


def fetch_one(db_path: Path, sql: str, params: tuple[Any, ...] = ()):
    conn = connect_db(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def fetch_counts(db_path: Path, project_id: str) -> dict[str, int]:
    conn = connect_db(db_path)
    try:
        return {
            "projects": conn.execute(
                "SELECT COUNT(*) FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()[0],
            "project_status_events": conn.execute(
                "SELECT COUNT(*) FROM project_status_events WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0],
            "artifacts": conn.execute(
                "SELECT COUNT(*) FROM artifacts WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0],
            "plans": conn.execute(
                "SELECT COUNT(*) FROM plans WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0],
            "timelines": conn.execute(
                "SELECT COUNT(*) FROM timelines WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0],
            "image_manifests": conn.execute(
                "SELECT COUNT(*) FROM image_manifests WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0],
            "scripts": conn.execute(
                "SELECT COUNT(*) FROM scripts WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0],
        }
    finally:
        conn.close()


def inspect_json(
    db_path: Path,
    projects_root: Path,
    project_id: str,
    capsys,
    *extra_args: str,
) -> tuple[int, dict[str, Any], str, str]:
    exit_code = main(
        [
            "inspect",
            "--db-path",
            str(db_path),
            "--projects-root",
            str(projects_root),
            "--project-id",
            project_id,
            "--json",
            *extra_args,
        ]
    )
    captured = capsys.readouterr()
    data = json.loads(captured.out) if captured.out.strip().startswith("{") else {}
    return exit_code, data, captured.out, captured.err


def test_json_inspect_happy_path(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)

    exit_code, data, _stdout, stderr = inspect_json(db_path, projects_root, project_id, capsys)

    assert exit_code == 0
    assert stderr == ""
    assert data["schema_version"] == "project_inspection.v2.1"
    assert data["project"]["project_id"] == project_id
    assert data["project"]["status"] == "script_generated"
    assert data["status_sequence"] == EXPECTED_SEQUENCE
    artifact_types = {row["artifact_type"] for row in data["artifacts"]}
    assert {"b_scene_plan", "timeline", "d_image_manifest", "e_script"}.issubset(
        artifact_types
    )
    assert data["artifact_problem_count"] == 0


def test_human_readable_inspect_happy_path(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)

    exit_code = main(
        [
            "inspect",
            "--db-path",
            str(db_path),
            "--projects-root",
            str(projects_root),
            "--project-id",
            project_id,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "Project inspection" in captured.out
    assert "read-only" in captured.out
    assert project_id in captured.out
    assert "script_generated" in captured.out
    assert "candidate_selected -> planned -> project_generated" in captured.out
    assert "Artifacts:" in captured.out
    assert "Artifact problems:" in captured.out
    assert "e_script.json" in captured.out


def test_inspect_does_not_mutate_db(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)
    before_counts = fetch_counts(db_path, project_id)
    before_project = dict(
        fetch_one(db_path, "SELECT status, created_at, updated_at FROM projects WHERE id = ?", (project_id,))
    )

    exit_code, data, _stdout, stderr = inspect_json(db_path, projects_root, project_id, capsys)

    assert exit_code == 0
    assert stderr == ""
    assert data["artifact_problem_count"] == 0
    assert fetch_counts(db_path, project_id) == before_counts
    after_project = dict(
        fetch_one(db_path, "SELECT status, created_at, updated_at FROM projects WHERE id = ?", (project_id,))
    )
    assert after_project == before_project


def test_inspect_does_not_create_missing_db(tmp_path, capsys) -> None:
    db_path = tmp_path / "missing.sqlite3"
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    exit_code = main(
        [
            "inspect",
            "--db-path",
            str(db_path),
            "--projects-root",
            str(projects_root),
            "--project-id",
            "PRJ_20260528_0001",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "database file does not exist" in captured.err
    assert not db_path.exists()
    assert "Project inspection" not in captured.out


def test_inspect_does_not_create_missing_projects_root(tmp_path, capsys) -> None:
    db_path = tmp_path / "existing.sqlite3"
    db_path.write_bytes(b"")
    projects_root = tmp_path / "missing-projects"

    exit_code = main(
        [
            "inspect",
            "--db-path",
            str(db_path),
            "--projects-root",
            str(projects_root),
            "--project-id",
            "PRJ_20260528_0001",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "projects root does not exist" in captured.err
    assert not projects_root.exists()
    assert "Project inspection" not in captured.out


def test_project_not_found_fails_without_mutation(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)
    before_counts = fetch_counts(db_path, project_id)

    exit_code = main(
        [
            "inspect",
            "--db-path",
            str(db_path),
            "--projects-root",
            str(projects_root),
            "--project-id",
            "PRJ_20260528_9999",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "project not found" in captured.err
    assert "Project inspection" not in captured.out
    assert fetch_counts(db_path, project_id) == before_counts


def test_json_stdout_is_clean(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)

    exit_code, data, stdout, stderr = inspect_json(db_path, projects_root, project_id, capsys)

    output = stdout.strip()
    assert exit_code == 0
    assert stderr == ""
    assert output.startswith("{")
    assert output.endswith("}")
    assert data["schema_version"] == "project_inspection.v2.1"
    assert "Project inspection" not in output


def test_missing_artifact_is_reported_and_strict_fails(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)
    before_counts = fetch_counts(db_path, project_id)
    (projects_root / project_id / "e_script.json").unlink()

    exit_code, data, _stdout, stderr = inspect_json(db_path, projects_root, project_id, capsys)

    assert exit_code == 0
    assert stderr == ""
    assert data["artifact_problem_count"] > 0
    missing_rows = [
        row for row in data["artifacts"] if row["relative_path"].endswith("e_script.json")
    ]
    assert missing_rows[0]["exists"] is False
    assert fetch_counts(db_path, project_id) == before_counts

    strict_exit_code, strict_data, _strict_stdout, strict_stderr = inspect_json(
        db_path,
        projects_root,
        project_id,
        capsys,
        "--strict",
    )
    assert strict_exit_code == 1
    assert strict_data["artifact_problem_count"] > 0
    assert "strict inspection failed" in strict_stderr
    assert fetch_counts(db_path, project_id) == before_counts


def test_hash_mismatch_is_reported_without_repair(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)
    before_counts = fetch_counts(db_path, project_id)
    before_artifact = fetch_one(
        db_path,
        "SELECT sha256 FROM artifacts WHERE project_id = ? AND artifact_type = ?",
        (project_id, "e_script"),
    )["sha256"]
    script_path = projects_root / project_id / "e_script.json"
    script_path.write_text(script_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    exit_code, data, _stdout, stderr = inspect_json(db_path, projects_root, project_id, capsys)

    assert exit_code == 0
    assert stderr == ""
    assert data["artifact_problem_count"] > 0
    e_row = next(row for row in data["artifacts"] if row["artifact_type"] == "e_script")
    assert e_row["sha256_matches"] is False
    assert e_row["verification_error"] == "sha256 mismatch"
    after_artifact = fetch_one(
        db_path,
        "SELECT sha256 FROM artifacts WHERE project_id = ? AND artifact_type = ?",
        (project_id, "e_script"),
    )["sha256"]
    assert after_artifact == before_artifact
    assert fetch_counts(db_path, project_id) == before_counts

    strict_exit_code, strict_data, _strict_stdout, strict_stderr = inspect_json(
        db_path,
        projects_root,
        project_id,
        capsys,
        "--strict",
    )
    assert strict_exit_code == 1
    assert strict_data["artifact_problem_count"] > 0
    assert "strict inspection failed" in strict_stderr


def test_unsafe_artifact_path_is_reported_without_reading_file(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)
    conn = connect_db(db_path)
    try:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(
            """
            INSERT INTO artifacts (
                project_id, artifact_type, relative_path, sha256, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_id,
                "unsafe_test",
                "../evil.txt",
                "0" * 64,
                "2026-05-28T09:00:00+09:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    before_counts = fetch_counts(db_path, project_id)

    exit_code, data, _stdout, stderr = inspect_json(db_path, projects_root, project_id, capsys)

    assert exit_code == 0
    assert stderr == ""
    unsafe_row = next(row for row in data["artifacts"] if row["artifact_type"] == "unsafe_test")
    assert unsafe_row["path_is_safe"] is False
    assert unsafe_row["exists"] is None
    assert unsafe_row["sha256_matches"] is None
    assert "unsafe path" in unsafe_row["verification_error"]
    assert data["artifact_problem_count"] > 0
    assert fetch_counts(db_path, project_id) == before_counts

    strict_exit_code, strict_data, _strict_stdout, strict_stderr = inspect_json(
        db_path,
        projects_root,
        project_id,
        capsys,
        "--strict",
    )
    assert strict_exit_code == 1
    assert strict_data["artifact_problem_count"] > 0
    assert "strict inspection failed" in strict_stderr


@pytest.mark.parametrize(
    "args",
    [
        ["inspect", "--projects-root", "projects", "--project-id", "PRJ_20260528_0001"],
        ["inspect", "--db-path", "db.sqlite3", "--project-id", "PRJ_20260528_0001"],
        ["inspect", "--db-path", "db.sqlite3", "--projects-root", "projects"],
    ],
)
def test_required_inspect_args_are_enforced(args: list[str], capsys) -> None:
    exit_code = main(args)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error" in captured.err
    assert "Project inspection" not in captured.out


def test_no_verify_files_skips_missing_file_problem(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)
    (projects_root / project_id / "e_script.json").unlink()

    exit_code, data, _stdout, stderr = inspect_json(
        db_path,
        projects_root,
        project_id,
        capsys,
        "--no-verify-files",
    )

    assert exit_code == 0
    assert stderr == ""
    e_row = next(row for row in data["artifacts"] if row["artifact_type"] == "e_script")
    assert e_row["exists"] is None
    assert e_row["sha256_matches"] is None
    assert data["artifact_problem_count"] == 0


def test_no_verify_hashes_skips_hash_problem(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_smoke_cli(tmp_path, capsys)
    script_path = projects_root / project_id / "e_script.json"
    script_path.write_text(script_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    exit_code, data, _stdout, stderr = inspect_json(
        db_path,
        projects_root,
        project_id,
        capsys,
        "--no-verify-hashes",
    )

    assert exit_code == 0
    assert stderr == ""
    e_row = next(row for row in data["artifacts"] if row["artifact_type"] == "e_script")
    assert e_row["exists"] is True
    assert e_row["sha256_matches"] is None
    assert data["artifact_problem_count"] == 0
