from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from shorts_pipeline.db import connect_db
from shorts_pipeline.dev_cli import main
from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider
from shorts_pipeline.smoke import run_local_smoke_pipeline


F_ARTIFACT_TYPES = (
    "kdenlive_project",
    "f_kdenlive_manifest",
    "manual_kdenlive_editing_guide",
)


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def run_script_generated_project(tmp_path: Path) -> tuple[Path, Path, str]:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    result = run_local_smoke_pipeline(
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
        b_provider=DevFakeBProvider(),
        e_provider=DevFakeEProvider(),
    )
    return db_path, projects_root, result.project_id


def f_output_paths(projects_root: Path, project_id: str) -> list[Path]:
    project_dir = projects_root / project_id
    return [
        project_dir / "project.kdenlive",
        project_dir / "f_kdenlive_manifest.json",
        project_dir / "notes" / "manual_kdenlive_editing.md",
    ]


def f_artifact_rows(db_path: Path, project_id: str) -> list[str]:
    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT artifact_type
            FROM artifacts
            WHERE project_id = ?
              AND artifact_type IN ({",".join("?" for _ in F_ARTIFACT_TYPES)})
            """,
            (project_id, *F_ARTIFACT_TYPES),
        ).fetchall()
    finally:
        conn.close()
    return [row["artifact_type"] for row in rows]


def project_status(db_path: Path, project_id: str) -> str:
    conn = connect_db(db_path)
    try:
        row = conn.execute("SELECT status FROM projects WHERE id = ?", (project_id,)).fetchone()
        assert row is not None
        return row["status"]
    finally:
        conn.close()


def update_project_status(db_path: Path, project_id: str, status: str) -> None:
    conn = connect_db(db_path)
    try:
        conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
        conn.commit()
    finally:
        conn.close()


def generate_kdenlive_args(
    db_path: Path,
    projects_root: Path,
    project_id: str,
    *,
    confirm: bool = True,
    json_output: bool = False,
) -> list[str]:
    args = [
        "generate-kdenlive",
        "--db-path",
        str(db_path),
        "--projects-root",
        str(projects_root),
        "--project-id",
        project_id,
    ]
    if confirm:
        args.append("--confirm-local-write")
    if json_output:
        args.append("--json")
    return args


def assert_no_f_outputs_or_artifacts(
    db_path: Path,
    projects_root: Path,
    project_id: str,
) -> None:
    for path in f_output_paths(projects_root, project_id):
        assert not path.exists()
    assert f_artifact_rows(db_path, project_id) == []


def test_json_generate_kdenlive_cli_happy_path(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    exit_code = main(
        generate_kdenlive_args(
            db_path,
            projects_root,
            project_id,
            json_output=True,
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    output = captured.out.strip()
    assert output.startswith("{")
    assert output.endswith("}")
    data = json.loads(output)
    assert data["schema_version"] == "f_kdenlive_project.v2.1"
    assert data["project_id"] == project_id
    assert data["kdenlive_project_path"] == "project.kdenlive"
    assert data["scene_count"] >= 4
    assert data["external_template_used"] is False
    assert data["rendering_performed"] is False
    assert "Kdenlive skeleton generated" not in output
    for path in f_output_paths(projects_root, project_id):
        assert path.is_file()


def test_human_readable_generate_kdenlive_cli_happy_path(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    exit_code = main(generate_kdenlive_args(db_path, projects_root, project_id))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "Kdenlive skeleton generated" in captured.out
    assert project_id in captured.out
    assert "project.kdenlive" in captured.out
    assert "f_kdenlive_manifest.json" in captured.out
    assert "manual_kdenlive_editing.md" in captured.out
    assert "Scenes:" in captured.out
    assert "Rendering performed: false" in captured.out


def test_missing_confirm_local_write_fails_without_outputs(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    exit_code = main(
        generate_kdenlive_args(
            db_path,
            projects_root,
            project_id,
            confirm=False,
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--confirm-local-write" in captured.err
    assert "Kdenlive skeleton generated" not in captured.out
    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)
    assert project_status(db_path, project_id) == "script_generated"


@pytest.mark.parametrize(
    "missing_flag",
    ["--db-path", "--projects-root", "--project-id"],
)
def test_required_generate_kdenlive_args_are_enforced(
    tmp_path,
    capsys,
    missing_flag: str,
) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    args = generate_kdenlive_args(db_path, projects_root, project_id)
    index = args.index(missing_flag)
    del args[index : index + 2]

    exit_code = main(args)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert missing_flag in captured.err
    assert "Kdenlive skeleton generated" not in captured.out
    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)


def test_unknown_project_fails_without_success_output(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    exit_code = main(
        generate_kdenlive_args(
            db_path,
            projects_root,
            "PRJ_20260529_9999",
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "project not found" in captured.err
    assert "Kdenlive skeleton generated" not in captured.out
    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)


def test_wrong_status_fails_without_outputs_or_status_change(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    update_project_status(db_path, project_id, "images_inserted")

    exit_code = main(generate_kdenlive_args(db_path, projects_root, project_id))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "script_generated" in captured.err
    assert "Kdenlive skeleton generated" not in captured.out
    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)
    assert project_status(db_path, project_id) == "images_inserted"


def test_json_stdout_is_clean(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    exit_code = main(
        generate_kdenlive_args(
            db_path,
            projects_root,
            project_id,
            json_output=True,
        )
    )

    captured = capsys.readouterr()
    output = captured.out.strip()
    assert exit_code == 0
    assert captured.err == ""
    assert output.startswith("{")
    assert output.endswith("}")
    assert json.loads(output)["schema_version"] == "f_kdenlive_project.v2.1"
    assert "Project ID:" not in output


def test_cli_reports_no_rendering_or_external_template_use(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    exit_code = main(
        generate_kdenlive_args(
            db_path,
            projects_root,
            project_id,
            json_output=True,
        )
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert exit_code == 0
    assert data["rendering_performed"] is False
    assert data["external_template_used"] is False
