"""Read-only verification for generated local project folders."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from shorts_pipeline.b_service import validate_b_scene_plan_against_source
from shorts_pipeline.c_service import validate_timeline_against_b_plan
from shorts_pipeline.d_service import validate_d_image_manifest_against_timeline
from shorts_pipeline.db import connect_readonly_db
from shorts_pipeline.e_service import validate_e_script_against_inputs
from shorts_pipeline.f_service import (
    validate_f_kdenlive_manifest_against_inputs,
    validate_generated_kdenlive_xml,
)
from shorts_pipeline.models import (
    BScenePlan,
    DImageManifest,
    EScript,
    FKdenliveManifest,
    ProjectFolderVerificationResult,
    ProjectVerificationItem,
    SourceArtifact,
    StrictModel,
    TimelineJson,
)
from shorts_pipeline.security import (
    SecurityValidationError,
    ensure_path_under_root,
    ensure_relative_project_path,
    sha256_file,
)

EXPECTED_PROJECT_STATUS = "script_generated"
F_ARTIFACT_TYPES = {
    "kdenlive_project",
    "f_kdenlive_manifest",
    "manual_kdenlive_editing_guide",
}
F_ARTIFACT_RELATIVE_PATHS = {
    "kdenlive_project": "project.kdenlive",
    "f_kdenlive_manifest": "f_kdenlive_manifest.json",
    "manual_kdenlive_editing_guide": "notes/manual_kdenlive_editing.md",
}


class ProjectVerificationError(ValueError):
    """Raised when a project-folder verification cannot be started."""


class ProjectNotFoundError(ProjectVerificationError):
    """Raised when the requested project row does not exist."""


def _load_project_row(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT id, project_dir, status
        FROM projects
        WHERE id = ?
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        raise ProjectNotFoundError(f"project not found: {project_id}")
    return row


def _load_artifact_rows(conn: sqlite3.Connection, project_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, project_id, artifact_type, relative_path, sha256, created_at
        FROM artifacts
        WHERE project_id = ?
        ORDER BY id
        """,
        (project_id,),
    ).fetchall()


def _resolve_project_dir(projects_root: Path, project_row: sqlite3.Row) -> Path:
    relative_project_dir = ensure_relative_project_path(project_row["project_dir"])
    root = Path(projects_root).resolve()
    return ensure_path_under_root(root, root / relative_project_dir)


def _safe_project_file(project_dir: Path, relative_path: str) -> Path:
    safe_relative_path = ensure_relative_project_path(relative_path)
    return ensure_path_under_root(project_dir, project_dir / safe_relative_path)


def _problem_count(items: list[ProjectVerificationItem]) -> int:
    return sum(1 for item in items if item.problem is not None or not item.valid)


def _add_item(
    items: list[ProjectVerificationItem],
    *,
    name: str,
    kind: str,
    required: bool,
    valid: bool,
    relative_path: str | None = None,
    exists: bool | None = None,
    sha256_matches: bool | None = None,
    problem: str | None = None,
) -> None:
    items.append(
        ProjectVerificationItem(
            name=name,
            relative_path=relative_path,
            kind=kind,
            exists=exists,
            valid=valid,
            required=required,
            sha256_matches=sha256_matches,
            problem=problem,
        )
    )


def _load_json_artifact(
    items: list[ProjectVerificationItem],
    *,
    project_dir: Path,
    relative_path: str,
    model: type[StrictModel],
    name: str,
) -> Any | None:
    try:
        path = _safe_project_file(project_dir, relative_path)
    except SecurityValidationError as exc:
        _add_item(
            items,
            name=name,
            kind="json_contract",
            relative_path=relative_path,
            exists=None,
            valid=False,
            required=True,
            problem=f"unsafe path: {exc}",
        )
        return None
    if not path.is_file():
        _add_item(
            items,
            name=name,
            kind="json_contract",
            relative_path=relative_path,
            exists=False,
            valid=False,
            required=True,
            problem="required JSON artifact is missing",
        )
        return None
    try:
        loaded = model.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        _add_item(
            items,
            name=name,
            kind="json_contract",
            relative_path=relative_path,
            exists=True,
            valid=False,
            required=True,
            problem=f"{exc.__class__.__name__}: {exc}",
        )
        return None
    _add_item(
        items,
        name=name,
        kind="json_contract",
        relative_path=relative_path,
        exists=True,
        valid=True,
        required=True,
    )
    return loaded


def _validate_file_exists(
    items: list[ProjectVerificationItem],
    *,
    project_dir: Path,
    relative_path: str,
    name: str,
    kind: str,
    required: bool,
) -> Path | None:
    try:
        path = _safe_project_file(project_dir, relative_path)
    except SecurityValidationError as exc:
        _add_item(
            items,
            name=name,
            kind=kind,
            relative_path=relative_path,
            exists=None,
            valid=not required,
            required=required,
            problem=f"unsafe path: {exc}",
        )
        return None
    exists = path.is_file()
    _add_item(
        items,
        name=name,
        kind=kind,
        relative_path=relative_path,
        exists=exists,
        valid=exists or not required,
        required=required,
        problem=None if exists or not required else "required file is missing",
    )
    return path if exists else None


def _validate_png_asset(
    items: list[ProjectVerificationItem],
    *,
    project_dir: Path,
    relative_path: str,
    name: str,
    require_alpha: bool,
) -> None:
    path = _validate_file_exists(
        items,
        project_dir=project_dir,
        relative_path=relative_path,
        name=name,
        kind="png_asset",
        required=True,
    )
    if path is None:
        return

    try:
        with Image.open(path) as image:
            format_name = image.format
            size = image.size
            mode = image.mode
            has_transparency = "transparency" in image.info or mode in {"RGBA", "LA"}
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        _add_item(
            items,
            name=f"{name}:png_validation",
            kind="png_asset_validation",
            relative_path=relative_path,
            exists=True,
            valid=False,
            required=True,
            problem=f"PNG validation failed: {exc}",
        )
        return

    problem: str | None = None
    if format_name != "PNG":
        problem = "asset is not a PNG"
    elif size != (1080, 1920):
        problem = "asset dimensions are not 1080x1920"
    elif require_alpha and not has_transparency:
        problem = "text overlay PNG does not expose an alpha channel"

    _add_item(
        items,
        name=f"{name}:png_validation",
        kind="png_asset_validation",
        relative_path=relative_path,
        exists=True,
        valid=problem is None,
        required=True,
        problem=problem,
    )


def _artifact_row_path(row: sqlite3.Row, projects_root: Path) -> tuple[Path | None, str | None]:
    try:
        safe_relative_path = ensure_relative_project_path(row["relative_path"])
        path = ensure_path_under_root(projects_root, projects_root / safe_relative_path)
    except SecurityValidationError as exc:
        return None, f"unsafe artifact path: {exc}"
    return path, None


def _check_artifact_row_safety_and_hash(
    items: list[ProjectVerificationItem],
    *,
    row: sqlite3.Row,
    projects_root: Path,
    verify_hashes: bool,
) -> None:
    path, problem = _artifact_row_path(row, projects_root)
    if problem is not None or path is None:
        _add_item(
            items,
            name=f"artifact_row:{row['artifact_type']}",
            kind="db_artifact_row",
            relative_path=row["relative_path"],
            exists=None,
            valid=False,
            required=True,
            sha256_matches=None,
            problem=problem,
        )
        return

    exists = path.is_file()
    sha256_matches: bool | None = None
    if not exists:
        problem = "artifact row points to a missing file"
    elif verify_hashes and row["sha256"]:
        sha256_matches = sha256_file(path) == row["sha256"]
        if not sha256_matches:
            problem = "sha256 mismatch"

    _add_item(
        items,
        name=f"artifact_row:{row['artifact_type']}",
        kind="db_artifact_row",
        relative_path=row["relative_path"],
        exists=exists,
        valid=problem is None,
        required=True,
        sha256_matches=sha256_matches,
        problem=problem,
    )


def _check_expected_artifact_row(
    items: list[ProjectVerificationItem],
    *,
    rows: list[sqlite3.Row],
    project_id: str,
    artifact_type: str,
    project_relative_path: str,
    required: bool,
) -> None:
    expected_relative_path = f"{project_id}/{project_relative_path}"
    matches = [
        row
        for row in rows
        if row["artifact_type"] == artifact_type and row["relative_path"] == expected_relative_path
    ]
    if not matches:
        _add_item(
            items,
            name=f"expected_artifact_row:{artifact_type}",
            kind="db_artifact_presence",
            relative_path=expected_relative_path,
            exists=False,
            valid=not required,
            required=required,
            problem=None if not required else "required artifact row is missing",
        )
        return

    _add_item(
        items,
        name=f"expected_artifact_row:{artifact_type}",
        kind="db_artifact_presence",
        relative_path=expected_relative_path,
        exists=True,
        valid=True,
        required=required,
    )


def _expected_a_to_e_artifact_rows(timeline: TimelineJson) -> list[tuple[str, str]]:
    expected = [
        ("b_scene_plan", "b_scene_plan.json"),
        ("timeline", "timeline.json"),
        ("d_image_manifest", "d_image_manifest.json"),
        ("e_script", "e_script.json"),
    ]
    for scene in timeline.scenes:
        expected.extend(
            [
                ("user_image_slot", scene.image_path),
                ("text_overlay", scene.text_overlay_path),
            ]
        )
    return expected


def _validate_optional_f_presence(
    items: list[ProjectVerificationItem],
    *,
    project_dir: Path,
) -> None:
    for artifact_type, relative_path in F_ARTIFACT_RELATIVE_PATHS.items():
        try:
            path = _safe_project_file(project_dir, relative_path)
        except SecurityValidationError as exc:
            _add_item(
                items,
                name=f"optional_f:{artifact_type}",
                kind="optional_f_artifact",
                relative_path=relative_path,
                exists=None,
                valid=False,
                required=False,
                problem=f"unsafe path: {exc}",
            )
            continue
        _add_item(
            items,
            name=f"optional_f:{artifact_type}",
            kind="optional_f_artifact",
            relative_path=relative_path,
            exists=path.is_file(),
            valid=True,
            required=False,
        )


def _validate_f_artifacts(
    items: list[ProjectVerificationItem],
    *,
    project_dir: Path,
    timeline: TimelineJson | None,
    d_manifest: DImageManifest | None,
    e_script: EScript | None,
) -> None:
    xml_path = _validate_file_exists(
        items,
        project_dir=project_dir,
        relative_path="project.kdenlive",
        name="project.kdenlive",
        kind="f_artifact",
        required=True,
    )
    manifest_path = _validate_file_exists(
        items,
        project_dir=project_dir,
        relative_path="f_kdenlive_manifest.json",
        name="f_kdenlive_manifest.json",
        kind="f_artifact",
        required=True,
    )
    _validate_file_exists(
        items,
        project_dir=project_dir,
        relative_path="notes/manual_kdenlive_editing.md",
        name="manual_kdenlive_editing.md",
        kind="f_artifact",
        required=True,
    )
    if manifest_path is None:
        return

    try:
        f_manifest = FKdenliveManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        _add_item(
            items,
            name="f_manifest_contract",
            kind="f_validation",
            relative_path="f_kdenlive_manifest.json",
            exists=True,
            valid=False,
            required=True,
            problem=f"{exc.__class__.__name__}: {exc}",
        )
        return

    _add_item(
        items,
        name="f_manifest_contract",
        kind="f_validation",
        relative_path="f_kdenlive_manifest.json",
        exists=True,
        valid=True,
        required=True,
    )

    if timeline is not None and d_manifest is not None and e_script is not None:
        try:
            validate_f_kdenlive_manifest_against_inputs(
                f_manifest,
                timeline=timeline,
                d_manifest=d_manifest,
                e_script=e_script,
            )
        except Exception as exc:
            _add_item(
                items,
                name="f_manifest_against_inputs",
                kind="f_validation",
                relative_path="f_kdenlive_manifest.json",
                exists=True,
                valid=False,
                required=True,
                problem=f"{exc.__class__.__name__}: {exc}",
            )
        else:
            _add_item(
                items,
                name="f_manifest_against_inputs",
                kind="f_validation",
                relative_path="f_kdenlive_manifest.json",
                exists=True,
                valid=True,
                required=True,
            )

    if xml_path is None:
        return
    try:
        validate_generated_kdenlive_xml(
            xml_path,
            project_root=project_dir,
            manifest=f_manifest,
        )
    except Exception as exc:
        _add_item(
            items,
            name="project.kdenlive_xml",
            kind="f_xml_validation",
            relative_path="project.kdenlive",
            exists=True,
            valid=False,
            required=True,
            problem=f"{exc.__class__.__name__}: {exc}",
        )
    else:
        _add_item(
            items,
            name="project.kdenlive_xml",
            kind="f_xml_validation",
            relative_path="project.kdenlive",
            exists=True,
            valid=True,
            required=True,
        )


def verify_generated_project_folder(
    *,
    db_path: Path,
    projects_root: Path,
    project_id: str,
    require_f: bool = False,
    verify_hashes: bool = True,
) -> ProjectFolderVerificationResult:
    """Verify an existing generated project folder without writing files or DB rows."""
    if not project_id:
        raise ProjectVerificationError("project_id is required")

    resolved_db_path = Path(db_path).expanduser().resolve()
    resolved_projects_root = Path(projects_root).expanduser().resolve()
    if not resolved_db_path.is_file():
        raise ProjectVerificationError(f"database file does not exist: {resolved_db_path}")
    if not resolved_projects_root.is_dir():
        raise ProjectVerificationError(f"projects root does not exist: {resolved_projects_root}")

    conn = connect_readonly_db(resolved_db_path)
    try:
        project_row = _load_project_row(conn, project_id)
        artifact_rows = _load_artifact_rows(conn, project_id)
    finally:
        conn.close()

    project_dir = _resolve_project_dir(resolved_projects_root, project_row)
    items: list[ProjectVerificationItem] = []
    warnings: list[str] = []

    if project_row["status"] != EXPECTED_PROJECT_STATUS:
        _add_item(
            items,
            name="project_status",
            kind="status",
            valid=False,
            required=True,
            problem=f"expected {EXPECTED_PROJECT_STATUS}, got {project_row['status']}",
        )
    else:
        _add_item(
            items,
            name="project_status",
            kind="status",
            valid=True,
            required=True,
        )

    source = _load_json_artifact(
        items,
        project_dir=project_dir,
        relative_path="source.json",
        model=SourceArtifact,
        name="source.json",
    )
    b_plan = _load_json_artifact(
        items,
        project_dir=project_dir,
        relative_path="b_scene_plan.json",
        model=BScenePlan,
        name="b_scene_plan.json",
    )
    timeline = _load_json_artifact(
        items,
        project_dir=project_dir,
        relative_path="timeline.json",
        model=TimelineJson,
        name="timeline.json",
    )
    d_manifest = _load_json_artifact(
        items,
        project_dir=project_dir,
        relative_path="d_image_manifest.json",
        model=DImageManifest,
        name="d_image_manifest.json",
    )
    e_script = _load_json_artifact(
        items,
        project_dir=project_dir,
        relative_path="e_script.json",
        model=EScript,
        name="e_script.json",
    )

    if isinstance(source, SourceArtifact) and source.project_id != project_id:
        _add_item(
            items,
            name="source_project_id",
            kind="json_cross_check",
            relative_path="source.json",
            exists=True,
            valid=False,
            required=True,
            problem="source.json project_id does not match requested project",
        )
    if isinstance(timeline, TimelineJson) and timeline.project_id != project_id:
        _add_item(
            items,
            name="timeline_project_id",
            kind="json_cross_check",
            relative_path="timeline.json",
            exists=True,
            valid=False,
            required=True,
            problem="timeline.json project_id does not match requested project",
        )
    if isinstance(d_manifest, DImageManifest) and d_manifest.project_id != project_id:
        _add_item(
            items,
            name="d_manifest_project_id",
            kind="json_cross_check",
            relative_path="d_image_manifest.json",
            exists=True,
            valid=False,
            required=True,
            problem="d_image_manifest.json project_id does not match requested project",
        )

    if isinstance(source, SourceArtifact) and isinstance(b_plan, BScenePlan):
        try:
            validate_b_scene_plan_against_source(b_plan, source)
        except Exception as exc:
            _add_item(
                items,
                name="b_scene_plan_against_source",
                kind="json_cross_check",
                relative_path="b_scene_plan.json",
                exists=True,
                valid=False,
                required=True,
                problem=f"{exc.__class__.__name__}: {exc}",
            )
        else:
            _add_item(
                items,
                name="b_scene_plan_against_source",
                kind="json_cross_check",
                relative_path="b_scene_plan.json",
                exists=True,
                valid=True,
                required=True,
            )
    if (
        isinstance(source, SourceArtifact)
        and isinstance(b_plan, BScenePlan)
        and isinstance(timeline, TimelineJson)
    ):
        try:
            validate_timeline_against_b_plan(timeline, b_plan, source)
        except Exception as exc:
            _add_item(
                items,
                name="timeline_against_b_plan",
                kind="json_cross_check",
                relative_path="timeline.json",
                exists=True,
                valid=False,
                required=True,
                problem=f"{exc.__class__.__name__}: {exc}",
            )
        else:
            _add_item(
                items,
                name="timeline_against_b_plan",
                kind="json_cross_check",
                relative_path="timeline.json",
                exists=True,
                valid=True,
                required=True,
            )
    if isinstance(timeline, TimelineJson) and isinstance(d_manifest, DImageManifest):
        try:
            d_manifest = validate_d_image_manifest_against_timeline(
                d_manifest,
                timeline,
                project_root=project_dir,
                require_ready_for_e=True,
            )
        except Exception as exc:
            _add_item(
                items,
                name="d_manifest_readiness",
                kind="json_cross_check",
                relative_path="d_image_manifest.json",
                exists=True,
                valid=False,
                required=True,
                problem=f"{exc.__class__.__name__}: {exc}",
            )
        else:
            _add_item(
                items,
                name="d_manifest_readiness",
                kind="json_cross_check",
                relative_path="d_image_manifest.json",
                exists=True,
                valid=True,
                required=True,
            )
    if (
        isinstance(source, SourceArtifact)
        and isinstance(timeline, TimelineJson)
        and isinstance(d_manifest, DImageManifest)
        and isinstance(e_script, EScript)
    ):
        try:
            validate_e_script_against_inputs(
                e_script,
                source=source,
                timeline=timeline,
                d_manifest=d_manifest,
            )
        except Exception as exc:
            _add_item(
                items,
                name="e_script_against_inputs",
                kind="json_cross_check",
                relative_path="e_script.json",
                exists=True,
                valid=False,
                required=True,
                problem=f"{exc.__class__.__name__}: {exc}",
            )
        else:
            _add_item(
                items,
                name="e_script_against_inputs",
                kind="json_cross_check",
                relative_path="e_script.json",
                exists=True,
                valid=True,
                required=True,
            )

    if isinstance(timeline, TimelineJson):
        for scene in timeline.scenes:
            _validate_png_asset(
                items,
                project_dir=project_dir,
                relative_path=scene.image_path,
                name=f"user_image:{scene.image_slot_id}",
                require_alpha=False,
            )
            _validate_png_asset(
                items,
                project_dir=project_dir,
                relative_path=scene.text_overlay_path,
                name=f"text_overlay:{scene.scene_id}",
                require_alpha=True,
            )

        for artifact_type, project_relative_path in _expected_a_to_e_artifact_rows(timeline):
            _check_expected_artifact_row(
                items,
                rows=artifact_rows,
                project_id=project_id,
                artifact_type=artifact_type,
                project_relative_path=project_relative_path,
                required=True,
            )

    for row in artifact_rows:
        if row["artifact_type"] in F_ARTIFACT_TYPES:
            continue
        _check_artifact_row_safety_and_hash(
            items,
            row=row,
            projects_root=resolved_projects_root,
            verify_hashes=verify_hashes,
        )

    a_to_e_problem_count = _problem_count(items)
    f_start_index = len(items)
    if require_f:
        _validate_f_artifacts(
            items,
            project_dir=project_dir,
            timeline=timeline if isinstance(timeline, TimelineJson) else None,
            d_manifest=d_manifest if isinstance(d_manifest, DImageManifest) else None,
            e_script=e_script if isinstance(e_script, EScript) else None,
        )
        for row in artifact_rows:
            if row["artifact_type"] not in F_ARTIFACT_TYPES:
                continue
            _check_artifact_row_safety_and_hash(
                items,
                row=row,
                projects_root=resolved_projects_root,
                verify_hashes=verify_hashes,
            )
        for artifact_type, project_relative_path in F_ARTIFACT_RELATIVE_PATHS.items():
            _check_expected_artifact_row(
                items,
                rows=artifact_rows,
                project_id=project_id,
                artifact_type=artifact_type,
                project_relative_path=project_relative_path,
                required=True,
            )
    else:
        _validate_optional_f_presence(items, project_dir=project_dir)

    f_problem_count = _problem_count(items[f_start_index:])
    return ProjectFolderVerificationResult(
        project_id=project_id,
        project_status=project_row["status"],
        require_f=require_f,
        verified_a_to_e=a_to_e_problem_count == 0,
        verified_f=require_f and f_problem_count == 0,
        problem_count=_problem_count(items),
        items=items,
        warnings=warnings[:50],
    )
