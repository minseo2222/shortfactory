"""Phase 3 C compiler prototype."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from shorts_pipeline.b_service import validate_b_scene_plan_against_source
from shorts_pipeline.config import KST
from shorts_pipeline.db import connect_db, init_db, insert_project_status_event
from shorts_pipeline.models import BScenePlan, SourceArtifact, TimelineJson
from shorts_pipeline.projectgen.placeholder import create_placeholder_png
from shorts_pipeline.projectgen.replace_images import build_replace_images_markdown
from shorts_pipeline.projectgen.text_overlay import create_text_overlay_png
from shorts_pipeline.projectgen.timeline import (
    TIMELINE_SOURCE_KEYS,
    build_timeline_from_b_plan,
)
from shorts_pipeline.security import (
    ensure_path_under_root,
    ensure_relative_project_path,
    sha256_file,
)
from shorts_pipeline.state_machine import assert_transition_allowed

TIMELINE_SCHEMA_VERSION = "timeline.v2.1"
REQUIRED_CURRENT_STATUS = "planned"
PROJECT_GENERATED_STATUS = "project_generated"

FORBIDDEN_TIMELINE_TERMS = (
    "full_text",
    "raw_html",
    "comments",
    "screenshot",
    "cookie",
    "api_key",
    "secret",
    "password",
    "token",
)


class ProjectNotFoundError(ValueError):
    """Raised when a project row does not exist."""


class ProjectStatusError(ValueError):
    """Raised when the project is not in the required status."""


class CCompilerInputError(ValueError):
    """Raised when source or B artifacts are missing or invalid."""


class TimelineValidationError(ValueError):
    """Raised when a timeline fails application-level C validation."""


def _now_kst(clock: Callable[[], datetime] | None = None) -> datetime:
    current = clock() if clock else datetime.now(tz=KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).replace(microsecond=0)


def _expected_scene_ids(count: int) -> list[str]:
    return [f"s{index:02d}" for index in range(1, count + 1)]


def _expected_slot_ids(count: int) -> list[str]:
    return [f"slot_{index:03d}" for index in range(1, count + 1)]


def _iter_keys_and_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.append(str(key))
            found.extend(_iter_keys_and_strings(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_keys_and_strings(child))
    elif isinstance(value, str):
        found.append(value)
    return found


def _load_project_row(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ProjectNotFoundError(f"project not found: {project_id}")
    return row


def _resolve_project_dir(projects_root: Path, project_row: sqlite3.Row) -> Path:
    relative_project_dir = ensure_relative_project_path(project_row["project_dir"])
    root = Path(projects_root).resolve()
    return ensure_path_under_root(root, root / relative_project_dir)


def _load_source_artifact(project_dir: Path, project_id: str) -> SourceArtifact:
    source_path = ensure_path_under_root(project_dir, project_dir / "source.json")
    if not source_path.exists():
        raise CCompilerInputError("source.json is missing")
    source = SourceArtifact.model_validate(json.loads(source_path.read_text(encoding="utf-8")))
    if source.project_id != project_id:
        raise CCompilerInputError("source.json project_id does not match project row")
    return source


def _load_b_scene_plan(project_dir: Path, source: SourceArtifact) -> BScenePlan:
    b_path = ensure_path_under_root(project_dir, project_dir / "b_scene_plan.json")
    if not b_path.exists():
        raise CCompilerInputError("b_scene_plan.json is missing")
    plan = BScenePlan.model_validate(json.loads(b_path.read_text(encoding="utf-8")))
    validate_b_scene_plan_against_source(plan, source)
    return plan


def _validate_timeline_path(path: str) -> None:
    ensure_relative_project_path(path)


def validate_timeline_against_b_plan(
    timeline: TimelineJson,
    b_plan: BScenePlan,
    source: SourceArtifact,
) -> None:
    """Apply deterministic C validation rules beyond Pydantic field checks."""
    if timeline.schema_version != TIMELINE_SCHEMA_VERSION:
        raise TimelineValidationError("schema_version must be timeline.v2.1")
    if not timeline.project_id or timeline.project_id != source.project_id:
        raise TimelineValidationError("timeline project_id must match source project_id")
    if timeline.canvas.width != 1080 or timeline.canvas.height != 1920 or timeline.canvas.fps != 30:
        raise TimelineValidationError("timeline canvas must be 1080x1920 at 30fps")
    if timeline.canvas.duration_target_sec != b_plan.target_duration_sec:
        raise TimelineValidationError("canvas duration target must match B target")
    if len(timeline.scenes) != len(b_plan.scene_plan):
        raise TimelineValidationError("timeline scene count must match B scene count")

    expected_start = 0.0
    expected_scene_ids = [scene.scene_id for scene in b_plan.scene_plan]
    actual_scene_ids = [scene.scene_id for scene in timeline.scenes]
    if actual_scene_ids != expected_scene_ids or actual_scene_ids != _expected_scene_ids(len(timeline.scenes)):
        raise TimelineValidationError("timeline scene order must match B scene order")

    actual_slot_ids = [scene.image_slot_id for scene in timeline.scenes]
    if actual_slot_ids != _expected_slot_ids(len(timeline.scenes)):
        raise TimelineValidationError("image slot ids must be consecutive")

    for timeline_scene, b_scene in zip(timeline.scenes, b_plan.scene_plan, strict=True):
        rounded_start = round(expected_start, 3)
        if abs(timeline_scene.start_sec - rounded_start) > 0.001:
            raise TimelineValidationError("start_sec must be cumulative and rounded")
        if abs(timeline_scene.duration_sec - b_scene.duration_sec) > 0.001:
            raise TimelineValidationError("timeline duration must match B scene duration")
        if timeline_scene.fact_basis != b_scene.source_basis:
            raise TimelineValidationError("timeline fact_basis must come from B source_basis")
        if timeline_scene.avoid_claims != b_scene.do_not_say:
            raise TimelineValidationError("timeline avoid_claims must come from B do_not_say")
        _validate_timeline_path(timeline_scene.image_path)
        _validate_timeline_path(timeline_scene.text_overlay_path)
        expected_start += timeline_scene.duration_sec

    total_duration = round(expected_start, 3)
    if abs(timeline.total_duration_sec - total_duration) > 0.001:
        raise TimelineValidationError("total_duration_sec must equal cumulative duration")
    if timeline.total_duration_sec < 30 or timeline.total_duration_sec > 60:
        raise TimelineValidationError("total_duration_sec must be 30 to 60 seconds")

    if set(timeline.source) != set(TIMELINE_SOURCE_KEYS):
        raise TimelineValidationError("timeline source contains keys outside the allowlist")

    for text in _iter_keys_and_strings(timeline.model_dump(mode="json")):
        lowered = text.casefold()
        if any(term in lowered for term in FORBIDDEN_TIMELINE_TERMS):
            raise TimelineValidationError("timeline contains forbidden raw-source/storage terms")


def write_timeline_json(project_dir: str | Path, timeline: TimelineJson) -> Path:
    """Write and re-validate timeline.json."""
    root = Path(project_dir).resolve()
    output_path = ensure_path_under_root(root, root / "timeline.json")
    data = timeline.model_dump(mode="json")
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    TimelineJson.model_validate(json.loads(output_path.read_text(encoding="utf-8")))
    return output_path


def _snapshot_files(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, previous_bytes in snapshot.items():
        if previous_bytes is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(previous_bytes)


def _write_readmes(project_dir: Path) -> list[Path]:
    readmes = {
        "assets/bgm/README.md": (
            "# BGM\n\n"
            "Place only user-approved local background music here in a later phase. "
            "No automatic audio download or insertion is performed.\n"
        ),
        "exports/README.md": (
            "# Exports\n\n"
            "Manual or later-phase rendered exports can be placed here. "
            "This compiler does not render media.\n"
        ),
    }
    written: list[Path] = []
    for relative_path, content in readmes.items():
        path = ensure_path_under_root(project_dir, project_dir / relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def _generate_c_files(project_dir: Path, timeline: TimelineJson) -> list[Path]:
    generated: list[Path] = []
    canvas = timeline.canvas
    for scene in timeline.scenes:
        placeholder_path = ensure_path_under_root(
            project_dir,
            project_dir
            / "assets"
            / "placeholders"
            / f"{scene.image_slot_id}_placeholder.png",
        )
        user_image_path = ensure_path_under_root(project_dir, project_dir / scene.image_path)
        overlay_path = ensure_path_under_root(project_dir, project_dir / scene.text_overlay_path)

        create_placeholder_png(
            scene.image_slot_id,
            placeholder_path,
            canvas,
            scene_id=scene.scene_id,
            image_slot_description=scene.image_slot_description,
            avoid_claims=scene.avoid_claims,
        )
        # Seed the user-image slot with a copy of the placeholder, but never
        # clobber a user-replaced image. C is `planned`-only so this normally
        # runs once; the guard makes a re-run safe (an existing slot file that
        # differs from the placeholder is treated as a user replacement and is
        # preserved).
        if (
            not user_image_path.exists()
            or user_image_path.read_bytes() == placeholder_path.read_bytes()
        ):
            shutil.copyfile(placeholder_path, user_image_path)
        create_text_overlay_png(scene.screen_text, overlay_path, canvas)
        generated.extend([placeholder_path, user_image_path, overlay_path])

    replace_guide_path = ensure_path_under_root(project_dir, project_dir / "notes" / "replace_images.md")
    replace_guide_path.write_text(
        build_replace_images_markdown(timeline.project_id, timeline),
        encoding="utf-8",
    )
    generated.append(replace_guide_path)
    generated.extend(_write_readmes(project_dir))
    generated.append(write_timeline_json(project_dir, timeline))
    return generated


def _artifact_rows_for_files(project_id: str, project_dir: Path, paths: list[Path]) -> list[tuple[str, str, str]]:
    artifact_rows: list[tuple[str, str, str]] = []
    for path in paths:
        relative_to_project = path.relative_to(project_dir).as_posix()
        relative_path = ensure_relative_project_path(f"{project_id}/{relative_to_project}").as_posix()
        if relative_to_project == "timeline.json":
            artifact_type = "timeline"
        elif relative_to_project.startswith("assets/placeholders/"):
            artifact_type = "placeholder_image"
        elif relative_to_project.startswith("assets/user_images/"):
            artifact_type = "user_image_slot"
        elif relative_to_project.startswith("assets/text_overlays/"):
            artifact_type = "text_overlay"
        elif relative_to_project == "notes/replace_images.md":
            artifact_type = "replace_images_guide"
        else:
            artifact_type = "readme"
        artifact_rows.append((artifact_type, relative_path, sha256_file(path)))
    return artifact_rows


def compile_c_project(
    project_id: str,
    *,
    db_path: Path,
    projects_root: Path,
    clock: Callable[[], datetime] | None = None,
) -> TimelineJson:
    """Compile local C artifacts for a planned project."""
    conn = connect_db(db_path)
    generated_paths: list[Path] = []
    snapshot: dict[Path, bytes | None] = {}
    try:
        init_db(conn)
        project_row = _load_project_row(conn, project_id)
        if project_row["status"] != REQUIRED_CURRENT_STATUS:
            raise ProjectStatusError("C compile requires planned status")
        project_dir = _resolve_project_dir(projects_root, project_row)
        source = _load_source_artifact(project_dir, project_id)
        b_plan = _load_b_scene_plan(project_dir, source)
        timeline = build_timeline_from_b_plan(b_plan, source=source, project_id=project_id)
        validate_timeline_against_b_plan(timeline, b_plan, source)

        planned_paths = [project_dir / "timeline.json", project_dir / "notes" / "replace_images.md"]
        planned_paths.extend([project_dir / "assets" / "bgm" / "README.md", project_dir / "exports" / "README.md"])
        for scene in timeline.scenes:
            planned_paths.extend(
                [
                    project_dir / "assets" / "placeholders" / f"{scene.image_slot_id}_placeholder.png",
                    project_dir / scene.image_path,
                    project_dir / scene.text_overlay_path,
                ]
            )
        safe_planned_paths = [ensure_path_under_root(project_dir, path) for path in planned_paths]
        snapshot = _snapshot_files(safe_planned_paths)

        conn.execute("BEGIN")
        current_row = _load_project_row(conn, project_id)
        if current_row["status"] != REQUIRED_CURRENT_STATUS:
            raise ProjectStatusError("project status changed before C persistence")
        assert_transition_allowed(current_row["status"], PROJECT_GENERATED_STATUS)

        generated_paths = _generate_c_files(project_dir, timeline)
        artifact_rows = _artifact_rows_for_files(project_id, project_dir, generated_paths)
        created_at = _now_kst(clock).isoformat()
        timeline_json = json.dumps(timeline.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        timeline_relative_path = ensure_relative_project_path(f"{project_id}/timeline.json").as_posix()

        conn.execute(
            """
            INSERT INTO timelines (
                project_id,
                schema_version,
                timeline_json,
                total_duration_sec,
                artifact_path,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                TIMELINE_SCHEMA_VERSION,
                timeline_json,
                timeline.total_duration_sec,
                timeline_relative_path,
                created_at,
            ),
        )
        conn.executemany(
            """
            INSERT INTO artifacts (
                project_id,
                artifact_type,
                relative_path,
                sha256,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (project_id, artifact_type, relative_path, digest, created_at)
                for artifact_type, relative_path, digest in artifact_rows
            ],
        )
        conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (PROJECT_GENERATED_STATUS, created_at, project_id),
        )
        insert_project_status_event(
            conn,
            project_id=project_id,
            from_status=current_row["status"],
            to_status=PROJECT_GENERATED_STATUS,
            stage="C",
            reason="timeline_compiled",
            created_at=created_at,
        )
        conn.commit()
        return timeline
    except Exception:
        conn.rollback()
        if snapshot:
            _restore_files(snapshot)
        else:
            for path in generated_paths:
                if path.exists():
                    path.unlink()
        raise
    finally:
        conn.close()
