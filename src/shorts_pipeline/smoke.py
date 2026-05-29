"""Local A -> B -> C -> D -> E integration smoke runner."""

from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from shorts_pipeline.b_service import generate_b_scene_plan
from shorts_pipeline.c_service import compile_c_project
from shorts_pipeline.config import KST
from shorts_pipeline.d_service import (
    assert_d_image_manifest_ready_for_e,
    confirm_d_image_manifest,
    initialize_d_image_manifest,
)
from shorts_pipeline.db import connect_db, init_db, list_project_status_events
from shorts_pipeline.e_service import generate_e_script
from shorts_pipeline.f_service import (
    generate_f_kdenlive_project,
    validate_generated_kdenlive_xml,
)
from shorts_pipeline.llm.b_provider import BScenePlanProvider
from shorts_pipeline.llm.e_provider import EScriptProvider
from shorts_pipeline.models import (
    BScenePlan,
    CandidateCard,
    DImageManifest,
    EScript,
    FKdenliveManifest,
    SmokeArtifactCheck,
    SmokeRunResult,
    SourceArtifact,
    TimelineJson,
)
from shorts_pipeline.project_service import create_project_from_candidate
from shorts_pipeline.security import (
    ensure_path_under_root,
    ensure_relative_project_path,
    sha256_file,
)

EXPECTED_STATUS_SEQUENCE = [
    "candidate_selected",
    "planned",
    "project_generated",
    "waiting_for_user_images",
    "images_inserted",
    "script_generated",
]

F_ARTIFACT_RELATIVE_PATHS = [
    ("kdenlive_project", "project.kdenlive"),
    ("f_kdenlive_manifest", "f_kdenlive_manifest.json"),
    ("manual_kdenlive_editing_guide", "notes/manual_kdenlive_editing.md"),
]


class SmokeProviderNotConfiguredError(ValueError):
    """Raised when the local smoke runner is called without injected providers."""


class SmokeVerificationError(ValueError):
    """Raised when a smoke run completes a step but fails local verification."""


def _now_kst(clock: Callable[[], datetime] | None = None) -> datetime:
    current = clock() if clock else datetime.now(tz=KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).replace(microsecond=0)


def build_smoke_candidate(clock: Callable[[], datetime] | None = None) -> CandidateCard:
    """Build the deterministic fictional manual fixture used by the smoke run."""
    collected_at = _now_kst(clock).isoformat()
    return CandidateCard(
        candidate_id="smoke_001",
        title="Fictional online discussion trend about a home tip",
        source_url="https://example.test/manual-fixture/smoke-001",
        community="manual_fixture",
        collected_at=collected_at,
        summary=(
            "A fictional home tip prompted mixed reactions about convenience and "
            "possible misunderstanding. This user-written summary keeps only safe "
            "minimal context."
        ),
        hook="Why did a small home tip become a discussion?",
        why_shortable=(
            "The setup, reaction split, and cautious conclusion fit a short scene sequence."
        ),
        risk_flags_for_user=[
            "real name and nickname inference prohibited",
            "direct source quotation prohibited",
            "original capture reuse prohibited",
        ],
        status="new",
    )


def _ready_manifest_payload_from_draft(draft: DImageManifest) -> dict[str, Any]:
    payload = draft.model_dump(mode="json")
    payload["image_insert_completed"] = True
    payload["user_confirmed"] = True
    payload["completed_at"] = None
    payload["warnings"] = list(payload.get("warnings", []))
    for slot in payload["slots"]:
        slot["status"] = "placeholder"
        slot["actual_image_note"] = (
            "App-generated neutral placeholder image used for the local smoke test."
        )
        slot["source_type"] = "app_generated_placeholder"
        slot["rights_confirmed_by_user"] = True
        slot["contains_face"] = False
        slot["face_rights_confirmed"] = None
        slot["contains_personal_info"] = False
        slot["contains_original_capture"] = False
        slot["contains_community_logo"] = False
        slot["image_sha256"] = None
    return payload


def _load_json_artifacts(project_dir: Path) -> tuple[SourceArtifact, BScenePlan, TimelineJson, DImageManifest, EScript]:
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
    return source, b_plan, timeline, manifest, script


def _artifact_relative_paths(timeline: TimelineJson) -> list[tuple[str, str]]:
    paths = [
        ("source", "source.json"),
        ("b_scene_plan", "b_scene_plan.json"),
        ("timeline", "timeline.json"),
        ("d_image_manifest", "d_image_manifest.json"),
        ("e_script", "e_script.json"),
        ("replace_images_guide", "notes/replace_images.md"),
        ("bgm_readme", "assets/bgm/README.md"),
        ("exports_readme", "exports/README.md"),
    ]
    for scene in timeline.scenes:
        paths.extend(
            [
                (
                    f"{scene.image_slot_id}_placeholder",
                    f"assets/placeholders/{scene.image_slot_id}_placeholder.png",
                ),
                (scene.image_slot_id, scene.image_path),
                (f"{scene.scene_id}_text", scene.text_overlay_path),
            ]
        )
    return paths


def _build_artifact_checks(project_dir: Path, timeline: TimelineJson) -> list[SmokeArtifactCheck]:
    checks: list[SmokeArtifactCheck] = []
    for name, relative_path in _artifact_relative_paths(timeline):
        safe_relative_path = ensure_relative_project_path(relative_path).as_posix()
        path = ensure_path_under_root(project_dir, project_dir / safe_relative_path)
        checks.append(
            SmokeArtifactCheck(
                name=name,
                relative_path=safe_relative_path,
                exists=path.is_file(),
                sha256=sha256_file(path) if path.is_file() else None,
            )
        )
    return checks


def _build_f_artifact_checks(project_dir: Path) -> list[SmokeArtifactCheck]:
    checks: list[SmokeArtifactCheck] = []
    for name, relative_path in F_ARTIFACT_RELATIVE_PATHS:
        safe_relative_path = ensure_relative_project_path(relative_path).as_posix()
        path = ensure_path_under_root(project_dir, project_dir / safe_relative_path)
        checks.append(
            SmokeArtifactCheck(
                name=name,
                relative_path=safe_relative_path,
                exists=path.is_file(),
                sha256=sha256_file(path) if path.is_file() else None,
            )
        )
    return checks


def _verify_f_outputs(project_dir: Path, manifest: FKdenliveManifest) -> None:
    manifest_path = ensure_path_under_root(project_dir, project_dir / "f_kdenlive_manifest.json")
    xml_path = ensure_path_under_root(project_dir, project_dir / "project.kdenlive")
    guide_path = ensure_path_under_root(
        project_dir,
        project_dir / "notes" / "manual_kdenlive_editing.md",
    )
    for path in (xml_path, manifest_path, guide_path):
        if not path.is_file():
            raise SmokeVerificationError(f"missing F artifact: {path.relative_to(project_dir)}")

    reloaded_manifest = FKdenliveManifest.model_validate(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    if reloaded_manifest != manifest:
        raise SmokeVerificationError("F manifest on disk does not match service result")
    if manifest.external_template_used:
        raise SmokeVerificationError("F manifest unexpectedly used an external template")
    if manifest.rendering_performed:
        raise SmokeVerificationError("F manifest unexpectedly reports rendering")

    try:
        xml_root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        raise SmokeVerificationError("project.kdenlive XML did not parse") from exc
    if xml_root.tag != "mlt":
        raise SmokeVerificationError("project.kdenlive root is not mlt")

    validate_generated_kdenlive_xml(xml_path, project_root=project_dir, manifest=manifest)


def _fetch_project_status(conn: sqlite3.Connection, project_id: str) -> str:
    row = conn.execute("SELECT status FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise SmokeVerificationError(f"project row is missing: {project_id}")
    return row["status"]


def _table_count(conn: sqlite3.Connection, table: str, project_id: str | None = None) -> int:
    if project_id is None:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]


def _verify_artifact_rows(conn: sqlite3.Connection, *, projects_root: Path, project_id: str) -> None:
    root = Path(projects_root).resolve()
    artifact_rows = conn.execute(
        """
        SELECT artifact_type, relative_path, sha256
        FROM artifacts
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchall()
    artifact_types = {row["artifact_type"] for row in artifact_rows}
    required_types = {"b_scene_plan", "timeline", "d_image_manifest", "e_script"}
    if not required_types.issubset(artifact_types):
        missing = ", ".join(sorted(required_types - artifact_types))
        raise SmokeVerificationError(f"missing artifact rows: {missing}")

    for row in artifact_rows:
        relative_path = ensure_relative_project_path(row["relative_path"])
        actual_path = ensure_path_under_root(root, root / relative_path)
        if not actual_path.is_file():
            raise SmokeVerificationError(f"artifact row points to missing file: {relative_path}")
        if row["sha256"] and row["sha256"] != sha256_file(actual_path):
            raise SmokeVerificationError(f"artifact sha256 mismatch: {relative_path}")


def _verify_f_artifact_rows(conn: sqlite3.Connection, *, projects_root: Path, project_id: str) -> None:
    root = Path(projects_root).resolve()
    expected_types = {name for name, _relative_path in F_ARTIFACT_RELATIVE_PATHS}
    rows = conn.execute(
        """
        SELECT artifact_type, relative_path, sha256
        FROM artifacts
        WHERE project_id = ?
          AND artifact_type IN (
            'kdenlive_project',
            'f_kdenlive_manifest',
            'manual_kdenlive_editing_guide'
          )
        """,
        (project_id,),
    ).fetchall()
    found_types = {row["artifact_type"] for row in rows}
    if found_types != expected_types:
        missing = ", ".join(sorted(expected_types - found_types))
        raise SmokeVerificationError(f"missing F artifact rows: {missing}")

    for row in rows:
        relative_path = ensure_relative_project_path(row["relative_path"])
        actual_path = ensure_path_under_root(root, root / relative_path)
        if not actual_path.is_file():
            raise SmokeVerificationError(f"F artifact row points to missing file: {relative_path}")
        if row["sha256"] != sha256_file(actual_path):
            raise SmokeVerificationError(f"F artifact sha256 mismatch: {relative_path}")


def _verify_db_records(conn: sqlite3.Connection, project_id: str) -> dict[str, int]:
    tables = [
        "projects",
        "plans",
        "timelines",
        "image_manifests",
        "scripts",
        "artifacts",
        "llm_runs",
        "project_status_events",
    ]
    counts = {
        table: (
            conn.execute("SELECT COUNT(*) FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
            if table == "projects"
            else _table_count(conn, table, project_id)
        )
        for table in tables
    }
    required_minimums = {
        "projects": 1,
        "plans": 1,
        "timelines": 1,
        "image_manifests": 1,
        "scripts": 1,
        "artifacts": 4,
        "llm_runs": 2,
        "project_status_events": len(EXPECTED_STATUS_SEQUENCE),
    }
    for table, minimum in required_minimums.items():
        if counts[table] < minimum:
            raise SmokeVerificationError(f"{table} has fewer rows than expected")
    return counts


def run_local_smoke_pipeline(
    *,
    db_path: Path,
    projects_root: Path,
    clock: Callable[[], datetime] | None = None,
    b_provider: BScenePlanProvider | None = None,
    e_provider: EScriptProvider | None = None,
    run_f: bool = False,
) -> SmokeRunResult:
    """Run one deterministic local fixture through A -> E, optionally verifying F."""
    if b_provider is None:
        raise SmokeProviderNotConfiguredError("B provider must be injected for smoke runs")
    if e_provider is None:
        raise SmokeProviderNotConfiguredError("E provider must be injected for smoke runs")

    conn = connect_db(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()

    project = create_project_from_candidate(
        build_smoke_candidate(clock),
        db_path=db_path,
        projects_root=projects_root,
        clock=clock,
    )
    project_id = project.project_id
    generate_b_scene_plan(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=b_provider,
        clock=clock,
    )
    timeline = compile_c_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=clock,
    )
    draft_manifest = initialize_d_image_manifest(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=clock,
    )
    confirm_d_image_manifest(
        project_id,
        _ready_manifest_payload_from_draft(draft_manifest),
        db_path=db_path,
        projects_root=projects_root,
        clock=clock,
    )
    assert_d_image_manifest_ready_for_e(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
    )
    generate_e_script(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=e_provider,
        clock=clock,
    )

    root = Path(projects_root).resolve()
    project_dir = ensure_path_under_root(root, root / project_id)
    _load_json_artifacts(project_dir)
    artifact_checks = _build_artifact_checks(project_dir, timeline)
    if run_f:
        f_manifest = generate_f_kdenlive_project(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            clock=clock,
        )
        _verify_f_outputs(project_dir, f_manifest)
        artifact_checks.extend(_build_f_artifact_checks(project_dir))
    if any(not check.exists for check in artifact_checks):
        missing = ", ".join(check.relative_path for check in artifact_checks if not check.exists)
        raise SmokeVerificationError(f"missing generated artifacts: {missing}")

    conn = connect_db(db_path)
    try:
        init_db(conn)
        final_status = _fetch_project_status(conn, project_id)
        if final_status != "script_generated":
            raise SmokeVerificationError("final project status is not script_generated")
        _verify_artifact_rows(conn, projects_root=projects_root, project_id=project_id)
        if run_f:
            _verify_f_artifact_rows(conn, projects_root=projects_root, project_id=project_id)
        counts = _verify_db_records(conn, project_id)
    finally:
        conn.close()

    events = list_project_status_events(db_path, project_id)
    status_sequence = [event.to_status for event in events]
    if status_sequence != EXPECTED_STATUS_SEQUENCE:
        raise SmokeVerificationError("status event sequence does not match A/B/C/D/E path")

    return SmokeRunResult(
        project_id=project_id,
        final_status=final_status,
        status_sequence=status_sequence,
        artifact_checks=artifact_checks,
        db_table_counts=counts,
    )
