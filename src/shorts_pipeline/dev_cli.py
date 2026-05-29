"""Dev-only CLI entry points for local verification."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from shorts_pipeline.config import KST
from shorts_pipeline.inspect import inspect_project
from shorts_pipeline.models import FKdenliveManifest, ProjectInspectionResult, SmokeRunResult

SUCCESS = 0
RUNTIME_ERROR = 1
CONFIG_ERROR = 2


class CliConfigurationError(ValueError):
    """Raised when CLI arguments are syntactically valid but unsafe to run."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shorts-pipeline-dev",
        description="Dev-only local utilities for Shorts Pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    smoke = subparsers.add_parser(
        "smoke",
        help="Run the local A -> B -> C -> D -> E smoke pipeline.",
    )
    smoke.add_argument("--db-path", required=True, help="SQLite DB path for the smoke run.")
    smoke.add_argument(
        "--projects-root",
        required=True,
        help="Projects root directory for generated local smoke files.",
    )
    smoke.add_argument(
        "--fixed-clock",
        help="Optional ISO datetime used for deterministic project IDs and timestamps.",
    )
    smoke.add_argument(
        "--use-fake-providers",
        action="store_true",
        help="Required explicit opt-in to deterministic dev-only fake providers.",
    )
    smoke.add_argument(
        "--json",
        action="store_true",
        help="Print only the SmokeRunResult JSON object to stdout.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Read-only inspection of one existing local project.",
    )
    inspect_parser.add_argument("--db-path", required=True, help="Existing SQLite DB path.")
    inspect_parser.add_argument(
        "--projects-root",
        required=True,
        help="Existing projects root directory.",
    )
    inspect_parser.add_argument("--project-id", required=True, help="Project ID to inspect.")
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the ProjectInspectionResult JSON object to stdout.",
    )
    inspect_parser.add_argument(
        "--no-verify-files",
        action="store_true",
        help="Skip artifact file existence checks.",
    )
    inspect_parser.add_argument(
        "--no-verify-hashes",
        action="store_true",
        help="Skip artifact SHA-256 checks.",
    )
    inspect_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if artifact verification reports any problem.",
    )

    kdenlive_parser = subparsers.add_parser(
        "generate-kdenlive",
        help="Generate local Phase F Kdenlive skeleton artifacts for one existing project.",
    )
    kdenlive_parser.add_argument("--db-path", required=True, help="Existing SQLite DB path.")
    kdenlive_parser.add_argument(
        "--projects-root",
        required=True,
        help="Existing projects root directory.",
    )
    kdenlive_parser.add_argument(
        "--project-id",
        required=True,
        help="Project ID in script_generated status.",
    )
    kdenlive_parser.add_argument(
        "--confirm-local-write",
        action="store_true",
        help=(
            "Required explicit confirmation that project.kdenlive and F artifacts "
            "will be written under the existing project folder."
        ),
    )
    kdenlive_parser.add_argument(
        "--json",
        action="store_true",
        help="Print only one Kdenlive skeleton summary JSON object to stdout.",
    )
    return parser


def _resolve_cli_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve()


def _clock_from_fixed_datetime(value: str | None) -> Callable[[], datetime] | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CliConfigurationError(f"invalid --fixed-clock ISO datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    parsed = parsed.astimezone(KST).replace(microsecond=0)
    return lambda: parsed


def _print_human_result(result: SmokeRunResult) -> None:
    print("Smoke pipeline completed (local/dev-only, fake providers)")
    print(f"Project ID: {result.project_id}")
    print(f"Final status: {result.final_status}")
    print(f"Status sequence: {' -> '.join(result.status_sequence)}")
    print(f"Artifacts checked: {len(result.artifact_checks)}")


def _print_human_inspection(result: ProjectInspectionResult) -> None:
    print("Project inspection (read-only)")
    print(f"Project ID: {result.project.project_id}")
    print(f"Current status: {result.project.status}")
    print(f"Status sequence: {' -> '.join(result.status_sequence)}")
    print(f"Artifacts: {len(result.artifacts)}")
    print(f"Artifact problems: {result.artifact_problem_count}")
    if result.warnings:
        print(f"Warnings: {'; '.join(result.warnings)}")
    print("artifact_type | relative_path | exists | sha256")
    for artifact in result.artifacts:
        exists = "skipped" if artifact.exists is None else str(artifact.exists).lower()
        digest = artifact.sha256 or ""
        print(f"{artifact.artifact_type} | {artifact.relative_path} | {exists} | {digest}")


def _kdenlive_summary_json(result: FKdenliveManifest) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "project_id": result.project_id,
        "kdenlive_project_path": result.kdenlive_project_path,
        "total_duration_sec": result.total_duration_sec,
        "total_frames": result.total_frames,
        "scene_count": len(result.scenes),
        "external_template_used": result.external_template_used,
        "rendering_performed": result.rendering_performed,
    }


def _print_human_kdenlive_result(result: FKdenliveManifest) -> None:
    print("Kdenlive skeleton generated (local/dev-only)")
    print(f"Project ID: {result.project_id}")
    print(f"Kdenlive project: {result.kdenlive_project_path}")
    print("Manifest: f_kdenlive_manifest.json")
    print("Manual guide: notes/manual_kdenlive_editing.md")
    print(f"Scenes: {len(result.scenes)}")
    print(f"Rendering performed: {str(result.rendering_performed).lower()}")


def _require_existing_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise CliConfigurationError(f"{label} does not exist: {path}")


def _require_existing_directory(path: Path, label: str) -> None:
    if not path.is_dir():
        raise CliConfigurationError(f"{label} does not exist: {path}")


def _run_smoke_command(args: argparse.Namespace) -> int:
    if not args.use_fake_providers:
        raise CliConfigurationError("--use-fake-providers is required for dev smoke CLI")

    from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider
    from shorts_pipeline.smoke import run_local_smoke_pipeline

    db_path = _resolve_cli_path(args.db_path)
    projects_root = _resolve_cli_path(args.projects_root)
    clock = _clock_from_fixed_datetime(args.fixed_clock)

    result = run_local_smoke_pipeline(
        db_path=db_path,
        projects_root=projects_root,
        clock=clock,
        b_provider=DevFakeBProvider(),
        e_provider=DevFakeEProvider(),
    )
    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        _print_human_result(result)
    return SUCCESS


def _run_generate_kdenlive_command(args: argparse.Namespace) -> int:
    if not args.confirm_local_write:
        raise CliConfigurationError(
            "--confirm-local-write is required because this command writes "
            "project.kdenlive and F artifacts"
        )

    from shorts_pipeline.f_service import generate_f_kdenlive_project

    db_path = _resolve_cli_path(args.db_path)
    projects_root = _resolve_cli_path(args.projects_root)
    _require_existing_file(db_path, "database file")
    _require_existing_directory(projects_root, "projects root")

    result = generate_f_kdenlive_project(
        args.project_id,
        db_path=db_path,
        projects_root=projects_root,
    )
    if args.json:
        print(json.dumps(_kdenlive_summary_json(result), indent=2, ensure_ascii=False))
    else:
        _print_human_kdenlive_result(result)
    return SUCCESS


def _run_inspect_command(args: argparse.Namespace) -> int:
    db_path = _resolve_cli_path(args.db_path)
    projects_root = _resolve_cli_path(args.projects_root)
    verify_files = not args.no_verify_files
    verify_hashes = verify_files and not args.no_verify_hashes

    result = inspect_project(
        db_path=db_path,
        projects_root=projects_root,
        project_id=args.project_id,
        verify_files=verify_files,
        verify_hashes=verify_hashes,
    )
    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        _print_human_inspection(result)

    if args.strict and result.artifact_problem_count:
        print(
            f"strict inspection failed: {result.artifact_problem_count} artifact problems",
            file=sys.stderr,
        )
        return RUNTIME_ERROR
    return SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code)

    try:
        if args.command == "smoke":
            return _run_smoke_command(args)
        if args.command == "inspect":
            return _run_inspect_command(args)
        if args.command == "generate-kdenlive":
            return _run_generate_kdenlive_command(args)
        parser.error(f"unknown command: {args.command}")
        return CONFIG_ERROR
    except CliConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return CONFIG_ERROR
    except Exception as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
