from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from shorts_pipeline.db import connect_db
from shorts_pipeline.dev_cli import main
from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider
from shorts_pipeline.security import sha256_file
from shorts_pipeline.smoke import run_local_smoke_pipeline


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def run_project_with_f(tmp_path: Path) -> tuple[Path, Path, str]:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    result = run_local_smoke_pipeline(
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
        b_provider=DevFakeBProvider(),
        e_provider=DevFakeEProvider(),
        run_f=True,
    )
    return db_path, projects_root, result.project_id


def verify_project_args(
    db_path: Path,
    projects_root: Path,
    project_id: str,
    *,
    require_f: bool = False,
    json_output: bool = False,
    verify_hashes: bool = True,
) -> list[str]:
    args = [
        "verify-project",
        "--db-path",
        str(db_path),
        "--projects-root",
        str(projects_root),
        "--project-id",
        project_id,
    ]
    if require_f:
        args.append("--require-f")
    if not verify_hashes:
        args.append("--no-verify-hashes")
    if json_output:
        args.append("--json")
    return args


def db_counts(db_path: Path, project_id: str) -> dict[str, int]:
    conn = connect_db(db_path)
    try:
        return {
            "projects": conn.execute(
                "SELECT COUNT(*) FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()[0],
            "artifacts": conn.execute(
                "SELECT COUNT(*) FROM artifacts WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0],
            "project_status_events": conn.execute(
                "SELECT COUNT(*) FROM project_status_events WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0],
        }
    finally:
        conn.close()


def file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_verify_project_cli_json_happy_path(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_project_with_f(tmp_path)

    exit_code = main(
        verify_project_args(
            db_path,
            projects_root,
            project_id,
            require_f=True,
            json_output=True,
        )
    )

    captured = capsys.readouterr()
    output = captured.out.strip()
    assert exit_code == 0
    assert captured.err == ""
    assert output.startswith("{")
    assert output.endswith("}")
    data = json.loads(output)
    assert data["schema_version"] == "project_folder_verification.v2.1"
    assert data["project_id"] == project_id
    assert data["project_status"] == "script_generated"
    assert data["require_f"] is True
    assert data["verified_a_to_e"] is True
    assert data["verified_f"] is True
    assert data["problem_count"] == 0
    assert "Project folder verification" not in output


def test_verify_project_cli_human_happy_path(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_project_with_f(tmp_path)

    exit_code = main(
        verify_project_args(
            db_path,
            projects_root,
            project_id,
            require_f=True,
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "Project folder verification" in captured.out
    assert project_id in captured.out
    assert "script_generated" in captured.out
    assert "A to E verified: true" in captured.out
    assert "F verified: true" in captured.out
    assert "Problems: 0" in captured.out
    assert "project.kdenlive" in captured.out
    assert "f_kdenlive_manifest.json" in captured.out
    assert "manual_kdenlive_editing.md" in captured.out


def test_verify_project_cli_problem_exit_code_and_no_mutation(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_project_with_f(tmp_path)
    (projects_root / project_id / "project.kdenlive").unlink()
    before_counts = db_counts(db_path, project_id)
    before_files = file_snapshot(projects_root / project_id)

    exit_code = main(
        verify_project_args(
            db_path,
            projects_root,
            project_id,
            require_f=True,
            json_output=True,
        )
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert data["problem_count"] > 0
    assert any(
        item["relative_path"] == "project.kdenlive" and item["problem"]
        for item in data["items"]
    )
    assert db_counts(db_path, project_id) == before_counts
    assert file_snapshot(projects_root / project_id) == before_files


def test_verify_project_cli_unknown_project_fails(tmp_path, capsys) -> None:
    db_path, projects_root, _project_id = run_project_with_f(tmp_path)

    exit_code = main(
        verify_project_args(
            db_path,
            projects_root,
            "PRJ_20260529_9999",
            require_f=True,
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "project not found" in captured.err
    assert "Project folder verification" not in captured.out


def test_verify_project_cli_no_verify_hashes_skips_hash_mismatch(tmp_path, capsys) -> None:
    db_path, projects_root, project_id = run_project_with_f(tmp_path)
    manifest_path = projects_root / project_id / "f_kdenlive_manifest.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        verify_project_args(
            db_path,
            projects_root,
            project_id,
            require_f=True,
            json_output=True,
            verify_hashes=False,
        )
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert exit_code == 0
    assert data["problem_count"] == 0
    assert all(item["sha256_matches"] is not False for item in data["items"])


@pytest.mark.parametrize(
    "missing_flag",
    ["--db-path", "--projects-root", "--project-id"],
)
def test_verify_project_cli_required_args_are_enforced(
    tmp_path,
    capsys,
    missing_flag: str,
) -> None:
    db_path, projects_root, project_id = run_project_with_f(tmp_path)
    args = verify_project_args(db_path, projects_root, project_id, require_f=True)
    index = args.index(missing_flag)
    del args[index : index + 2]

    exit_code = main(args)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert missing_flag in captured.err
    assert "Project folder verification" not in captured.out


def test_verify_project_help_is_available(capsys) -> None:
    exit_code = main(["verify-project", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "--db-path" in captured.out
    assert "--projects-root" in captured.out
    assert "--project-id" in captured.out
    assert "--require-f" in captured.out
    assert "--no-verify-hashes" in captured.out
    assert "--json" in captured.out
