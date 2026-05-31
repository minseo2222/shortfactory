from __future__ import annotations

import json

from shorts_pipeline.dev_cli import main

EXPECTED_SEQUENCE = [
    "candidate_selected",
    "planned",
    "project_generated",
    "waiting_for_user_images",
    "images_inserted",
    "script_generated",
]
F_ARTIFACT_NAMES = {
    "kdenlive_project",
    "f_kdenlive_manifest",
    "manual_kdenlive_editing_guide",
}


def test_json_smoke_cli_happy_path(tmp_path, capsys) -> None:
    db_path = tmp_path / "db" / "smoke.sqlite3"
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
    assert data["schema_version"] == "smoke_run.v2.1"
    assert data["project_id"] == "PRJ_20260528_0001"
    assert data["final_status"] == "script_generated"
    assert data["status_sequence"] == EXPECTED_SEQUENCE
    assert F_ARTIFACT_NAMES.isdisjoint(
        {check["name"] for check in data["artifact_checks"]}
    )
    assert db_path.is_file()
    assert projects_root.is_dir()
    project_dir = projects_root / data["project_id"]
    assert not (project_dir / "project.kdenlive").exists()
    assert not (project_dir / "f_kdenlive_manifest.json").exists()
    assert not (project_dir / "notes" / "manual_kdenlive_editing.md").exists()


def test_human_readable_smoke_cli_happy_path(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "smoke",
            "--db-path",
            str(tmp_path / "db.sqlite3"),
            "--projects-root",
            str(tmp_path / "projects"),
            "--use-fake-providers",
            "--fixed-clock",
            "2026-05-28T09:00:00+09:00",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "Smoke pipeline completed" in captured.out
    assert "local/dev-only" in captured.out
    assert "PRJ_20260528_0001" in captured.out
    assert "script_generated" in captured.out
    assert "candidate_selected -> planned -> project_generated" in captured.out
    assert "Artifacts checked:" in captured.out
    assert "F Kdenlive skeleton generated" not in captured.out
    assert not captured.out.lstrip().startswith("{")


def test_json_smoke_cli_with_run_f_generates_f_artifacts(tmp_path, capsys) -> None:
    db_path = tmp_path / "db" / "smoke.sqlite3"
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
            "--run-f",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["final_status"] == "script_generated"
    assert F_ARTIFACT_NAMES.issubset(
        {check["name"] for check in data["artifact_checks"]}
    )
    project_dir = projects_root / data["project_id"]
    assert (project_dir / "project.kdenlive").is_file()
    assert (project_dir / "f_kdenlive_manifest.json").is_file()
    assert (project_dir / "notes" / "manual_kdenlive_editing.md").is_file()


def test_human_smoke_cli_with_run_f_mentions_kdenlive(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "smoke",
            "--db-path",
            str(tmp_path / "db.sqlite3"),
            "--projects-root",
            str(tmp_path / "projects"),
            "--use-fake-providers",
            "--fixed-clock",
            "2026-05-28T09:00:00+09:00",
            "--run-f",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "Smoke pipeline completed" in captured.out
    assert "PRJ_20260528_0001" in captured.out
    assert "script_generated" in captured.out
    assert "F Kdenlive skeleton generated: true" in captured.out
    assert "Rendering performed: false" in captured.out


def test_missing_fake_provider_flag_fails(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "smoke",
            "--db-path",
            str(tmp_path / "db.sqlite3"),
            "--projects-root",
            str(tmp_path / "projects"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--use-fake-providers" in captured.err
    assert "script_generated" not in captured.out
    assert not (tmp_path / "db.sqlite3").exists()


def test_run_f_still_requires_fake_provider_flag(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "smoke",
            "--db-path",
            str(tmp_path / "db.sqlite3"),
            "--projects-root",
            str(tmp_path / "projects"),
            "--run-f",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--use-fake-providers" in captured.err
    assert "script_generated" not in captured.out
    assert not (tmp_path / "db.sqlite3").exists()


def test_invalid_fixed_clock_fails(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "smoke",
            "--db-path",
            str(tmp_path / "db.sqlite3"),
            "--projects-root",
            str(tmp_path / "projects"),
            "--use-fake-providers",
            "--fixed-clock",
            "not-a-date",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "invalid --fixed-clock" in captured.err
    assert "Smoke pipeline completed" not in captured.out


def test_missing_required_paths_fail(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "smoke",
            "--db-path",
            str(tmp_path / "db.sqlite3"),
            "--use-fake-providers",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--projects-root" in captured.err
    assert "Smoke pipeline completed" not in captured.out


def test_cli_creates_local_dev_directories(tmp_path, capsys) -> None:
    db_path = tmp_path / "nested" / "db" / "smoke.sqlite3"
    projects_root = tmp_path / "nested" / "projects"

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
    assert db_path.parent.is_dir()
    assert db_path.is_file()
    assert projects_root.is_dir()
    data = json.loads(captured.out)
    project_dir = projects_root / data["project_id"]
    assert project_dir.is_dir()
    assert project_dir.resolve().is_relative_to(projects_root.resolve())


def test_json_mode_stdout_is_clean(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "smoke",
            "--db-path",
            str(tmp_path / "db.sqlite3"),
            "--projects-root",
            str(tmp_path / "projects"),
            "--use-fake-providers",
            "--fixed-clock",
            "2026-05-28T09:00:00+09:00",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    output = captured.out.strip()
    assert output.startswith("{")
    assert output.endswith("}")
    assert json.loads(output)["final_status"] == "script_generated"
    assert "Smoke pipeline completed" not in output
    assert captured.err == ""


def test_module_help_smoke_subcommand_is_available(capsys) -> None:
    exit_code = main(["--help"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "smoke" in captured.out
    assert "verify-project" in captured.out


def test_smoke_help_includes_run_f_flag(capsys) -> None:
    exit_code = main(["smoke", "--help"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "--run-f" in captured.out
