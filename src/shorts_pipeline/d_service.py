"""Phase 4 D image manifest workflow."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from shorts_pipeline.config import KST
from shorts_pipeline.db import connect_db, init_db, insert_project_status_event
from shorts_pipeline.models import DImageManifest, TimelineJson
from shorts_pipeline.security import (
    ensure_path_under_root,
    ensure_relative_project_path,
    sha256_file,
)
from shorts_pipeline.state_machine import assert_transition_allowed

D_SCHEMA_VERSION = "d_image_manifest.v2.1"
DRAFT_STATUS_FROM = "project_generated"
DRAFT_STATUS_TO = "waiting_for_user_images"
CONFIRM_ALLOWED_STATUSES = {"waiting_for_user_images", "project_generated"}
CONFIRM_STATUS_TO = "images_inserted"

FORBIDDEN_D_TERMS = (
    "full_text",
    "raw_html",
    "comments",
    "comment_dump",
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


class DImageManifestInputError(ValueError):
    """Raised when timeline or manifest input is missing or invalid."""


class DImageManifestValidationError(ValueError):
    """Raised when a D manifest fails application-level validation."""


def _now_kst(clock: Callable[[], datetime] | None = None) -> datetime:
    current = clock() if clock else datetime.now(tz=KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).replace(microsecond=0)


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


def _load_timeline(project_dir: Path, project_id: str) -> TimelineJson:
    timeline_path = ensure_path_under_root(project_dir, project_dir / "timeline.json")
    if not timeline_path.exists():
        raise DImageManifestInputError("timeline.json is missing")
    timeline = TimelineJson.model_validate(json.loads(timeline_path.read_text(encoding="utf-8")))
    if timeline.project_id != project_id:
        raise DImageManifestInputError("timeline.json project_id does not match project row")
    return timeline


def _load_d_manifest(project_dir: Path) -> DImageManifest:
    manifest_path = ensure_path_under_root(project_dir, project_dir / "d_image_manifest.json")
    if not manifest_path.exists():
        raise DImageManifestInputError("d_image_manifest.json is missing")
    return DImageManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))


def _snapshot_file(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _restore_file(path: Path, snapshot: bytes | None) -> None:
    if snapshot is None:
        if path.exists():
            path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(snapshot)


def _assert_png_slot_image(path: Path) -> None:
    if not path.exists():
        raise DImageManifestValidationError(f"actual image file is missing: {path.name}")
    if not path.is_file():
        raise DImageManifestValidationError("actual image path must be a file")
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise DImageManifestValidationError("actual image must be PNG")
            if image.size != (1080, 1920):
                raise DImageManifestValidationError("actual image must be 1080x1920")
            image.verify()
    except UnidentifiedImageError as exc:
        raise DImageManifestValidationError("actual image must be loadable") from exc


def _validate_forbidden_terms(manifest: DImageManifest) -> None:
    for text in _iter_keys_and_strings(manifest.model_dump(mode="json")):
        lowered = text.casefold()
        if any(term in lowered for term in FORBIDDEN_D_TERMS):
            raise DImageManifestValidationError("D manifest contains forbidden raw-source terms")


def validate_d_image_manifest_against_timeline(
    manifest: DImageManifest,
    timeline: TimelineJson,
    *,
    project_root: Path,
    require_ready_for_e: bool,
) -> DImageManifest:
    """Validate and return a normalized D manifest with verified image hashes."""
    if manifest.schema_version != D_SCHEMA_VERSION:
        raise DImageManifestValidationError("schema_version must be d_image_manifest.v2.1")
    if manifest.project_id != timeline.project_id:
        raise DImageManifestValidationError("manifest project_id must match timeline")
    if len(manifest.slots) != len(timeline.scenes):
        raise DImageManifestValidationError("slot count must match timeline scene count")

    slot_updates: list[dict[str, Any]] = []
    project_dir = Path(project_root).resolve()
    for slot, scene in zip(manifest.slots, timeline.scenes, strict=True):
        if slot.slot_id != scene.image_slot_id or slot.scene_id != scene.scene_id:
            raise DImageManifestValidationError("manifest slot order must match timeline")

        ensure_relative_project_path(slot.planned_image_path)
        ensure_relative_project_path(slot.actual_image_path)
        if slot.planned_image_path != scene.image_path:
            raise DImageManifestValidationError("planned_image_path must match timeline image_path")

        actual_path = ensure_path_under_root(project_dir, project_dir / slot.actual_image_path)
        _assert_png_slot_image(actual_path)
        digest = sha256_file(actual_path)
        if slot.image_sha256 is not None and slot.image_sha256 != digest:
            raise DImageManifestValidationError("image_sha256 does not match actual image")

        if slot.status == "replaced":
            if not (slot.actual_image_note or "").strip():
                raise DImageManifestValidationError("replaced slots require actual_image_note")
            if slot.source_type == "app_generated_placeholder":
                raise DImageManifestValidationError(
                    "replaced slots require a non-placeholder source_type"
                )

        if slot.status == "placeholder" and slot.actual_image_note == "":
            slot.actual_image_note = None

        if require_ready_for_e:
            if not manifest.image_insert_completed:
                raise DImageManifestValidationError("image_insert_completed is required")
            if not manifest.user_confirmed:
                raise DImageManifestValidationError("user_confirmed is required")
            if manifest.completed_at is None:
                raise DImageManifestValidationError("completed_at is required")
            if not slot.rights_confirmed_by_user:
                raise DImageManifestValidationError("rights confirmation is required")
            if slot.contains_face and slot.face_rights_confirmed is not True:
                raise DImageManifestValidationError("face rights confirmation is required")
            if slot.contains_personal_info:
                raise DImageManifestValidationError("personal information blocks E readiness")
            if slot.contains_original_capture:
                raise DImageManifestValidationError("original captures block E readiness")
            if slot.contains_community_logo:
                raise DImageManifestValidationError("community logos block E readiness")

        slot_data = slot.model_dump(mode="json")
        slot_data["image_sha256"] = digest
        slot_updates.append(slot_data)

    _validate_forbidden_terms(manifest)
    manifest_data = manifest.model_dump(mode="json")
    manifest_data["slots"] = slot_updates
    return DImageManifest.model_validate(manifest_data)


def build_draft_image_manifest(
    *,
    timeline: TimelineJson,
    project_root: Path,
) -> DImageManifest:
    """Build a draft D manifest from timeline image slots."""
    slots: list[dict[str, Any]] = []
    for scene in timeline.scenes:
        image_path = ensure_path_under_root(project_root, project_root / scene.image_path)
        digest = sha256_file(image_path) if image_path.exists() else None
        slots.append(
            {
                "slot_id": scene.image_slot_id,
                "scene_id": scene.scene_id,
                "status": "placeholder",
                "planned_image_path": scene.image_path,
                "actual_image_path": scene.image_path,
                "actual_image_note": None,
                "source_type": "app_generated_placeholder",
                "rights_confirmed_by_user": False,
                "contains_face": False,
                "face_rights_confirmed": None,
                "contains_personal_info": False,
                "contains_original_capture": False,
                "contains_community_logo": False,
                "image_sha256": digest,
            }
        )
    return DImageManifest(project_id=timeline.project_id, slots=slots)


def _write_manifest_json(project_dir: Path, manifest: DImageManifest) -> Path:
    manifest_path = ensure_path_under_root(project_dir, project_dir / "d_image_manifest.json")
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    DImageManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    return manifest_path


def _upsert_d_artifact_and_manifest(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    manifest: DImageManifest,
    manifest_path: Path,
    project_dir: Path,
    created_at: str,
) -> None:
    relative_path = ensure_relative_project_path(
        f"{project_id}/{manifest_path.relative_to(project_dir).as_posix()}"
    ).as_posix()
    digest = sha256_file(manifest_path)
    manifest_json = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    existing_artifact = conn.execute(
        "SELECT id FROM artifacts WHERE project_id = ? AND artifact_type = ?",
        (project_id, "d_image_manifest"),
    ).fetchone()
    if existing_artifact is None:
        conn.execute(
            """
            INSERT INTO artifacts (
                project_id,
                artifact_type,
                relative_path,
                sha256,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, "d_image_manifest", relative_path, digest, created_at),
        )
    else:
        conn.execute(
            """
            UPDATE artifacts
            SET relative_path = ?, sha256 = ?, created_at = ?
            WHERE id = ?
            """,
            (relative_path, digest, created_at, existing_artifact["id"]),
        )
    conn.execute(
        """
        INSERT INTO image_manifests (
            project_id,
            schema_version,
            manifest_json,
            artifact_path,
            created_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET
            schema_version = excluded.schema_version,
            manifest_json = excluded.manifest_json,
            artifact_path = excluded.artifact_path,
            created_at = excluded.created_at
        """,
        (project_id, D_SCHEMA_VERSION, manifest_json, relative_path, created_at),
    )


def initialize_d_image_manifest(
    project_id: str,
    *,
    db_path: Path,
    projects_root: Path,
    clock: Callable[[], datetime] | None = None,
) -> DImageManifest:
    """Create a draft D image manifest and move the project to image-waiting state."""
    conn = connect_db(db_path)
    manifest_path: Path | None = None
    previous_manifest: bytes | None = None
    try:
        init_db(conn)
        project_row = _load_project_row(conn, project_id)
        if project_row["status"] != DRAFT_STATUS_FROM:
            raise ProjectStatusError("D draft initialization requires project_generated status")
        project_dir = _resolve_project_dir(projects_root, project_row)
        timeline = _load_timeline(project_dir, project_id)
        manifest = build_draft_image_manifest(timeline=timeline, project_root=project_dir)
        manifest = validate_d_image_manifest_against_timeline(
            manifest,
            timeline,
            project_root=project_dir,
            require_ready_for_e=False,
        )

        manifest_path = ensure_path_under_root(project_dir, project_dir / "d_image_manifest.json")
        previous_manifest = _snapshot_file(manifest_path)

        conn.execute("BEGIN")
        current_row = _load_project_row(conn, project_id)
        if current_row["status"] != DRAFT_STATUS_FROM:
            raise ProjectStatusError("project status changed before D draft persistence")
        assert_transition_allowed(current_row["status"], DRAFT_STATUS_TO)
        written_path = _write_manifest_json(project_dir, manifest)
        created_at = _now_kst(clock).isoformat()
        _upsert_d_artifact_and_manifest(
            conn,
            project_id=project_id,
            manifest=manifest,
            manifest_path=written_path,
            project_dir=project_dir,
            created_at=created_at,
        )
        conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (DRAFT_STATUS_TO, created_at, project_id),
        )
        insert_project_status_event(
            conn,
            project_id=project_id,
            from_status=current_row["status"],
            to_status=DRAFT_STATUS_TO,
            stage="D",
            reason="image_manifest_draft_initialized",
            created_at=created_at,
        )
        conn.commit()
        return manifest
    except Exception:
        conn.rollback()
        if manifest_path is not None:
            _restore_file(manifest_path, previous_manifest)
        raise
    finally:
        conn.close()


def _coerce_manifest(payload: Mapping[str, Any] | DImageManifest) -> DImageManifest:
    if isinstance(payload, DImageManifest):
        return payload
    return DImageManifest.model_validate(payload)


def confirm_d_image_manifest(
    project_id: str,
    manifest_payload: Mapping[str, Any] | DImageManifest,
    *,
    db_path: Path,
    projects_root: Path,
    clock: Callable[[], datetime] | None = None,
) -> DImageManifest:
    """Validate and persist a ready D image manifest."""
    conn = connect_db(db_path)
    manifest_path: Path | None = None
    previous_manifest: bytes | None = None
    try:
        init_db(conn)
        project_row = _load_project_row(conn, project_id)
        if project_row["status"] not in CONFIRM_ALLOWED_STATUSES:
            raise ProjectStatusError("D confirmation requires image-waiting or generated status")
        project_dir = _resolve_project_dir(projects_root, project_row)
        timeline = _load_timeline(project_dir, project_id)
        manifest = _coerce_manifest(manifest_payload)
        if manifest.project_id != project_id:
            raise DImageManifestValidationError("manifest project_id does not match project row")
        if manifest.image_insert_completed and manifest.user_confirmed and manifest.completed_at is None:
            manifest_data = manifest.model_dump(mode="json")
            manifest_data["completed_at"] = _now_kst(clock).isoformat()
            manifest = DImageManifest.model_validate(manifest_data)

        manifest = validate_d_image_manifest_against_timeline(
            manifest,
            timeline,
            project_root=project_dir,
            require_ready_for_e=True,
        )

        manifest_path = ensure_path_under_root(project_dir, project_dir / "d_image_manifest.json")
        previous_manifest = _snapshot_file(manifest_path)

        conn.execute("BEGIN")
        current_row = _load_project_row(conn, project_id)
        if current_row["status"] not in CONFIRM_ALLOWED_STATUSES:
            raise ProjectStatusError("project status changed before D confirmation")
        assert_transition_allowed(current_row["status"], CONFIRM_STATUS_TO)
        written_path = _write_manifest_json(project_dir, manifest)
        created_at = _now_kst(clock).isoformat()
        _upsert_d_artifact_and_manifest(
            conn,
            project_id=project_id,
            manifest=manifest,
            manifest_path=written_path,
            project_dir=project_dir,
            created_at=created_at,
        )
        conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (CONFIRM_STATUS_TO, created_at, project_id),
        )
        insert_project_status_event(
            conn,
            project_id=project_id,
            from_status=current_row["status"],
            to_status=CONFIRM_STATUS_TO,
            stage="D",
            reason="image_manifest_confirmed",
            created_at=created_at,
        )
        conn.commit()
        return manifest
    except Exception:
        conn.rollback()
        if manifest_path is not None:
            _restore_file(manifest_path, previous_manifest)
        raise
    finally:
        conn.close()


def assert_d_image_manifest_ready_for_e(
    project_id: str,
    *,
    db_path: Path,
    projects_root: Path,
) -> DImageManifest:
    """Load and validate the D manifest as the readiness gate for future E generation."""
    conn = connect_db(db_path)
    try:
        init_db(conn)
        project_row = _load_project_row(conn, project_id)
        if project_row["status"] != CONFIRM_STATUS_TO:
            raise ProjectStatusError("E readiness requires images_inserted status")
        project_dir = _resolve_project_dir(projects_root, project_row)
        timeline = _load_timeline(project_dir, project_id)
        manifest = _load_d_manifest(project_dir)
        return validate_d_image_manifest_against_timeline(
            manifest,
            timeline,
            project_root=project_dir,
            require_ready_for_e=True,
        )
    finally:
        conn.close()
