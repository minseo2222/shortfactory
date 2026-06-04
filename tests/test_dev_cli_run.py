"""Tests for the ``run`` dev CLI command (real-LLM/automation entry point).

All tests stay offline: they either force the deterministic fake providers or
assert the explicit-configuration guard fires before any provider is built. No
network egress, no rendering, no upload.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from shorts_pipeline import dev_cli
from shorts_pipeline.smoke import build_smoke_candidate

_FIXED_CLOCK = "2026-06-04T10:00:00"
_REAL_LLM_ENV = (
    "SHORTS_PIPELINE_ENABLE_REAL_LLM",
    "SHORTS_PIPELINE_LLM_BACKEND",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


def _paths(tmp_path: Path) -> list[str]:
    return [
        "--db-path",
        str(tmp_path / "db.sqlite3"),
        "--projects-root",
        str(tmp_path / "projects"),
    ]


def test_run_fake_full_pipeline_completes(tmp_path, capsys) -> None:
    code = dev_cli.main(
        [
            "run",
            *_paths(tmp_path),
            "--use-fake-providers",
            "--accept-placeholders",
            "--fixed-clock",
            _FIXED_CLOCK,
            "--json",
        ]
    )
    assert code == dev_cli.SUCCESS
    summary = json.loads(capsys.readouterr().out)
    assert summary["completed"] is True
    assert summary["stopped_at"] is None
    assert summary["rendering_performed"] is False
    assert summary["provider_mode"].startswith("fake")

    project_dir = Path(summary["project_dir"])
    assert (project_dir / "project.kdenlive").is_file()
    assert (project_dir / "f_kdenlive_manifest.json").is_file()


def test_run_fake_stops_at_d_without_accept(tmp_path, capsys) -> None:
    code = dev_cli.main(
        [
            "run",
            *_paths(tmp_path),
            "--use-fake-providers",
            "--fixed-clock",
            _FIXED_CLOCK,
            "--json",
        ]
    )
    assert code == dev_cli.SUCCESS
    summary = json.loads(capsys.readouterr().out)
    assert summary["completed"] is False
    assert summary["status"] == "project_generated"
    assert "D" in summary["stopped_at"]

    project_dir = Path(summary["project_dir"])
    assert not (project_dir / "project.kdenlive").exists()


def test_run_requires_explicit_provider_choice(tmp_path, capsys, monkeypatch) -> None:
    for name in _REAL_LLM_ENV:
        monkeypatch.delenv(name, raising=False)

    code = dev_cli.main(
        [
            "run",
            *_paths(tmp_path),
            "--accept-placeholders",
            "--fixed-clock",
            _FIXED_CLOCK,
        ]
    )
    assert code == dev_cli.CONFIG_ERROR
    err = capsys.readouterr().err
    assert "real LLM is not configured" in err
    assert "--use-fake-providers" in err
    # Nothing should have been created.
    assert not (tmp_path / "projects").exists() or not any((tmp_path / "projects").iterdir())


def test_run_uses_supplied_candidate_json(tmp_path, capsys) -> None:
    candidate = build_smoke_candidate(lambda: datetime(2026, 6, 4))
    payload = candidate.model_dump(mode="json")
    payload["title"] = "Supplied candidate title"
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")

    code = dev_cli.main(
        [
            "run",
            *_paths(tmp_path),
            "--candidate-json",
            str(candidate_path),
            "--use-fake-providers",
            "--accept-placeholders",
            "--fixed-clock",
            _FIXED_CLOCK,
            "--json",
        ]
    )
    assert code == dev_cli.SUCCESS
    summary = json.loads(capsys.readouterr().out)
    assert summary["completed"] is True
    assert (Path(summary["project_dir"]) / "project.kdenlive").is_file()
