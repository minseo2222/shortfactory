"""Dev-only CLI entry points for local verification."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from shorts_pipeline.config import KST, load_local_env
from shorts_pipeline.inspect import inspect_project
from shorts_pipeline.models import (
    FKdenliveManifest,
    ProjectInspectionResult,
    SmokeRunResult,
)

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
    smoke.add_argument(
        "--db-path",
        required=True,
        help="SQLite DB path for the smoke run.",
    )
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
        "--run-f",
        action="store_true",
        help=(
            "Optionally run Phase F after E and verify local Kdenlive handoff "
            "artifacts. Does not render or run Kdenlive/melt."
        ),
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
    inspect_parser.add_argument(
        "--db-path",
        required=True,
        help="Existing SQLite DB path.",
    )
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
    kdenlive_parser.add_argument(
        "--db-path",
        required=True,
        help="Existing SQLite DB path.",
    )
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

    run_parser = subparsers.add_parser(
        "run",
        help=(
            "Run the A -> C (or full A -> F with --accept-placeholders) pipeline "
            "for one candidate using the opt-in real LLM, or fake providers."
        ),
    )
    run_parser.add_argument("--db-path", required=True, help="SQLite DB path for the run.")
    run_parser.add_argument(
        "--projects-root",
        required=True,
        help="Projects root directory for generated local files.",
    )
    run_parser.add_argument(
        "--candidate-json",
        help=(
            "Path to a CandidateCard JSON file. When omitted, a built-in sample "
            "candidate is used (useful for a fake-provider dry run)."
        ),
    )
    run_parser.add_argument(
        "--use-fake-providers",
        action="store_true",
        help=(
            "Force the deterministic dev-only fake providers (offline). When "
            "omitted, the opt-in real LLM must be configured via environment."
        ),
    )
    run_parser.add_argument(
        "--accept-placeholders",
        action="store_true",
        help=(
            "Auto-confirm the D image manifest from generated placeholder slots "
            "(a dry-run handoff) and run E -> F to completion. Without this flag "
            "the run stops at the D human image/rights gate. No image is acquired, "
            "no TTS, no MP4 render, no upload."
        ),
    )
    run_parser.add_argument(
        "--fixed-clock",
        help="Optional ISO datetime used for deterministic project IDs and timestamps.",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the run summary JSON object to stdout.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Report local readiness: provider opt-in and optional dependencies.",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the readiness JSON object to stdout.",
    )
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the real LLM is not fully configured.",
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
    artifact_names = {check.name for check in result.artifact_checks}
    if {
        "kdenlive_project",
        "f_kdenlive_manifest",
        "manual_kdenlive_editing_guide",
    }.issubset(artifact_names):
        print("F Kdenlive skeleton generated: true")
        print("Rendering performed: false")


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
        run_f=args.run_f,
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


def _load_candidate(candidate_json: str | None, clock) -> dict[str, object]:
    if candidate_json is None:
        from shorts_pipeline.smoke import build_smoke_candidate

        return build_smoke_candidate(clock).model_dump(mode="json")

    path = _resolve_cli_path(candidate_json)
    _require_existing_file(path, "candidate JSON file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise CliConfigurationError(f"could not read candidate JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CliConfigurationError("candidate JSON must be a single object")
    return data


def _resolve_run_providers(use_fake: bool):
    """Return (b_provider, e_provider, mode_label), enforcing an explicit choice.

    Fake providers require ``--use-fake-providers``. Otherwise the opt-in real
    LLM must be fully configured; we never silently fall back to fakes here.
    """
    if use_fake:
        from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider

        return DevFakeBProvider(), DevFakeEProvider(), "fake (dev-only, deterministic, offline)"

    from shorts_pipeline.llm.real_providers import (
        resolve_b_provider,
        resolve_e_provider,
        selected_backend,
    )

    b_provider = resolve_b_provider()
    e_provider = resolve_e_provider()
    if b_provider is None or e_provider is None:
        raise CliConfigurationError(
            "real LLM is not configured. Set SHORTS_PIPELINE_ENABLE_REAL_LLM=1, "
            "select a backend, and provide the API key (see docs), or pass "
            "--use-fake-providers for an offline dry run."
        )
    return b_provider, e_provider, f"real:{selected_backend()}"


def _run_pipeline_command(args: argparse.Namespace) -> int:
    from shorts_pipeline.ui.controller import PipelineConfig, run_pipeline

    db_path = _resolve_cli_path(args.db_path)
    projects_root = _resolve_cli_path(args.projects_root)
    clock = _clock_from_fixed_datetime(args.fixed_clock)
    candidate = _load_candidate(args.candidate_json, clock)
    b_provider, e_provider, mode_label = _resolve_run_providers(args.use_fake_providers)

    config = PipelineConfig(db_path=db_path, projects_root=projects_root)
    result = run_pipeline(
        config,
        candidate,
        b_provider=b_provider,
        e_provider=e_provider,
        accept_placeholders=args.accept_placeholders,
        clock=clock,
    )
    summary = {
        "project_id": result["project_id"],
        "status": result["status"],
        "completed": result["completed"],
        "stopped_at": result["stopped_at"],
        "provider_mode": mode_label,
        "project_dir": str(projects_root / result["project_id"]),
        "rendering_performed": False,
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return SUCCESS

    print(f"Pipeline run completed (provider mode: {mode_label})")
    print(f"Project ID: {summary['project_id']}")
    print(f"Final status: {summary['status']}")
    print(f"Project folder: {summary['project_dir']}")
    if result["completed"]:
        print("Phases run: A -> B -> C -> D(placeholders) -> E -> F")
        print("Kdenlive handoff: project.kdenlive (no rendering, no upload performed)")
        print(
            "Next: open the project folder, replace placeholder images under "
            "assets/user_images/ with your rights-cleared images, then open "
            "project.kdenlive in Kdenlive."
        )
    else:
        print(f"Stopped at: {result['stopped_at']}")
        print(
            "Next: add your rights-cleared images under assets/user_images/, then "
            "confirm the D rights gate in the Streamlit UI (which continues E -> F), "
            "or re-run with --accept-placeholders for a placeholder dry run."
        )
    return SUCCESS


def _run_doctor_command(args: argparse.Namespace) -> int:
    import importlib.util

    from shorts_pipeline.llm.real_providers import provider_readiness

    def _is_installed(module_name: str) -> bool:
        # find_spec raises ModuleNotFoundError when a parent package (e.g.
        # "google") is absent, rather than returning None; treat that as missing.
        try:
            return importlib.util.find_spec(module_name) is not None
        except ModuleNotFoundError:
            return False

    from shorts_pipeline.sources.naver import naver_enabled
    from shorts_pipeline.sources.youtube import youtube_enabled

    info = provider_readiness()  # secret-free: presence and env var names only
    optional_deps = {
        name: _is_installed(name)
        for name in ("streamlit", "openai", "anthropic", "google.generativeai")
    }
    # Source-discovery readiness: presence of keys only, never their values.
    sources_ready = {
        "rss": True,  # no key required
        "single_link": True,  # no key required
        "youtube": youtube_enabled(),
        "naver": naver_enabled(),
    }
    summary = {
        "provider_mode": info["mode"],
        "real_ready": info["ready"],
        "real_enabled": info["real_enabled"],
        "backend": info["backend"],
        "key_present": info["key_present"],
        "missing": info["missing"],
        "optional_deps_installed": optional_deps,
        "sources_ready": sources_ready,
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print("Shorts Pipeline readiness (no secret values are shown)")
        print(f"Provider mode: {summary['provider_mode']}")
        print(f"Real LLM ready: {summary['real_ready']}")
        print(f"API key present: {summary['key_present']}")
        if summary["missing"]:
            print("To enable the real LLM:")
            for item in summary["missing"]:
                print(f"  - {item}")
        print("Optional dependencies:")
        for name, installed in optional_deps.items():
            print(f"  - {name}: {'installed' if installed else 'missing'}")
        print("Source discovery:")
        for name, ready in sources_ready.items():
            print(f"  - {name}: {'ready' if ready else 'needs key'}")

    if args.strict and not info["ready"]:
        print("strict doctor: real LLM is not fully configured", file=sys.stderr)
        return RUNTIME_ERROR
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
    load_local_env()
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code)

    try:
        if args.command == "smoke":
            return _run_smoke_command(args)
        if args.command == "run":
            return _run_pipeline_command(args)
        if args.command == "doctor":
            return _run_doctor_command(args)
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
