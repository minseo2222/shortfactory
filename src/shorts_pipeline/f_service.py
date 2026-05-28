"""Phase 6/F self-generated Kdenlive project skeleton service."""

from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from shorts_pipeline.config import KST
from shorts_pipeline.d_service import validate_d_image_manifest_against_timeline
from shorts_pipeline.db import connect_db, init_db
from shorts_pipeline.e_service import validate_e_script_against_inputs
from shorts_pipeline.models import (
    DImageManifest,
    EScript,
    FKdenliveManifest,
    SourceArtifact,
    TimelineJson,
)
from shorts_pipeline.projectgen.kdenlive import write_kdenlive_project_xml
from shorts_pipeline.security import (
    SecurityValidationError,
    ensure_path_under_root,
    ensure_relative_project_path,
    sha256_file,
)

F_SCHEMA_VERSION = "f_kdenlive_project.v2.1"
REQUIRED_CURRENT_STATUS = "script_generated"
FPS = 30
F_ARTIFACTS = {
    "kdenlive_project": "project.kdenlive",
    "f_kdenlive_manifest": "f_kdenlive_manifest.json",
    "manual_kdenlive_editing_guide": "notes/manual_kdenlive_editing.md",
}
SOURCE_ARTIFACTS = {
    "source": "source.json",
    "timeline": "timeline.json",
    "d_image_manifest": "d_image_manifest.json",
    "e_script": "e_script.json",
}
FORBIDDEN_XML_TERMS = (
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


class FKdenliveInputError(ValueError):
    """Raised when an F input artifact is missing or invalid."""


class FKdenliveValidationError(ValueError):
    """Raised when the F manifest or XML fails application validation."""


def _now_kst(clock: Callable[[], datetime] | None = None) -> datetime:
    current = clock() if clock else datetime.now(tz=KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).replace(microsecond=0)


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
    path = ensure_path_under_root(project_dir, project_dir / "source.json")
    if not path.is_file():
        raise FKdenliveInputError("source.json is missing")
    source = SourceArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if source.project_id != project_id:
        raise FKdenliveInputError("source.json project_id does not match project row")
    return source


def _load_timeline(project_dir: Path, project_id: str) -> TimelineJson:
    path = ensure_path_under_root(project_dir, project_dir / "timeline.json")
    if not path.is_file():
        raise FKdenliveInputError("timeline.json is missing")
    timeline = TimelineJson.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if timeline.project_id != project_id:
        raise FKdenliveInputError("timeline.json project_id does not match project row")
    return timeline


def _load_d_manifest(project_dir: Path, project_id: str) -> DImageManifest:
    path = ensure_path_under_root(project_dir, project_dir / "d_image_manifest.json")
    if not path.is_file():
        raise FKdenliveInputError("d_image_manifest.json is missing")
    manifest = DImageManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if manifest.project_id != project_id:
        raise FKdenliveInputError("d_image_manifest.json project_id does not match project row")
    return manifest


def _load_e_script(project_dir: Path) -> EScript:
    path = ensure_path_under_root(project_dir, project_dir / "e_script.json")
    if not path.is_file():
        raise FKdenliveInputError("e_script.json is missing")
    return EScript.model_validate(json.loads(path.read_text(encoding="utf-8")))


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


def _ensure_safe_existing_resource(project_root: Path, relative_path: str) -> Path:
    safe_relative_path = ensure_relative_project_path(relative_path)
    path = ensure_path_under_root(project_root, project_root / safe_relative_path)
    if not path.is_file():
        raise FKdenliveValidationError(f"referenced resource is missing: {relative_path}")
    return path


def _iter_xml_strings(root: ET.Element) -> list[str]:
    strings: list[str] = []
    for element in root.iter():
        strings.append(str(element.tag))
        if element.text:
            strings.append(element.text)
        if element.tail:
            strings.append(element.tail)
        for key, value in element.attrib.items():
            strings.extend([str(key), str(value)])
    return strings


def _producer_resource(producer: ET.Element) -> str | None:
    for property_element in producer.findall("property"):
        if property_element.attrib.get("name") == "resource":
            return property_element.text or ""
    return None


def validate_f_kdenlive_manifest_against_inputs(
    manifest: FKdenliveManifest,
    *,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
    e_script: EScript,
) -> None:
    """Apply deterministic F manifest validation rules beyond Pydantic checks."""
    if manifest.schema_version != F_SCHEMA_VERSION:
        raise FKdenliveValidationError("schema_version must be f_kdenlive_project.v2.1")
    if manifest.project_id != timeline.project_id:
        raise FKdenliveValidationError("manifest project_id must match timeline")
    if d_manifest.project_id != timeline.project_id:
        raise FKdenliveValidationError("D manifest project_id must match timeline")
    if manifest.canvas_width != 1080 or manifest.canvas_height != 1920 or manifest.fps != FPS:
        raise FKdenliveValidationError("manifest canvas must be 1080x1920 at 30fps")
    if abs(manifest.total_duration_sec - timeline.total_duration_sec) > 0.001:
        raise FKdenliveValidationError("manifest duration must match timeline")
    if manifest.total_frames != round(timeline.total_duration_sec * manifest.fps):
        raise FKdenliveValidationError("manifest total_frames must match timeline")
    if len(manifest.scenes) != len(timeline.scenes):
        raise FKdenliveValidationError("manifest scene count must match timeline")
    if manifest.source_artifacts != SOURCE_ARTIFACTS:
        raise FKdenliveValidationError("source_artifacts must reference canonical F inputs")
    if manifest.external_template_used:
        raise FKdenliveValidationError("external templates must not be used")
    if manifest.rendering_performed:
        raise FKdenliveValidationError("rendering must not be performed")

    narration_scene_ids = {line.scene_id for line in e_script.narration_script}
    slots_by_scene = {slot.scene_id: slot for slot in d_manifest.slots}
    for index, (scene_ref, timeline_scene) in enumerate(
        zip(manifest.scenes, timeline.scenes, strict=True),
        start=1,
    ):
        if scene_ref.scene_id != timeline_scene.scene_id:
            raise FKdenliveValidationError("scene order must match timeline")
        if scene_ref.image_slot_id != timeline_scene.image_slot_id:
            raise FKdenliveValidationError("image slot ids must match timeline")
        slot = slots_by_scene.get(timeline_scene.scene_id)
        if slot is None:
            raise FKdenliveValidationError("D manifest is missing a scene slot")
        if scene_ref.image_path != slot.actual_image_path:
            raise FKdenliveValidationError("image path must match D actual_image_path")
        if scene_ref.text_overlay_path != timeline_scene.text_overlay_path:
            raise FKdenliveValidationError("text overlay path must match timeline")
        if scene_ref.start_frame != round(timeline_scene.start_sec * manifest.fps):
            raise FKdenliveValidationError("start_frame must be deterministic")
        if scene_ref.duration_frames != round(timeline_scene.duration_sec * manifest.fps):
            raise FKdenliveValidationError("duration_frames must be deterministic")
        if scene_ref.scene_id not in narration_scene_ids or not scene_ref.narration_script_present:
            raise FKdenliveValidationError("each scene requires E narration")
        if scene_ref.image_slot_id != f"slot_{index:03d}":
            raise FKdenliveValidationError("image slots must remain in sequence")
        ensure_relative_project_path(scene_ref.image_path)
        ensure_relative_project_path(scene_ref.text_overlay_path)

    for path in manifest.source_artifacts.values():
        ensure_relative_project_path(path)


def validate_generated_kdenlive_xml(
    xml_path: Path,
    *,
    project_root: Path,
    manifest: FKdenliveManifest,
) -> None:
    """Validate the safety and structure contract for the self-generated XML."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        raise FKdenliveValidationError("generated Kdenlive XML does not parse") from exc
    root = tree.getroot()
    if root.tag != "mlt":
        raise FKdenliveValidationError("generated Kdenlive XML root must be mlt")

    profiles = root.findall("profile")
    if not profiles:
        raise FKdenliveValidationError("generated Kdenlive XML requires a profile")
    profile = profiles[0]
    if profile.attrib.get("width") != "1080" or profile.attrib.get("height") != "1920":
        raise FKdenliveValidationError("generated Kdenlive profile must be 1080x1920")
    if profile.attrib.get("frame_rate_num") != "30" or profile.attrib.get("frame_rate_den") != "1":
        raise FKdenliveValidationError("generated Kdenlive profile must be 30fps")
    if len(root.findall("playlist")) < 2:
        raise FKdenliveValidationError("generated Kdenlive XML requires image and text playlists")
    if root.find("tractor") is None or root.find(".//multitrack") is None:
        raise FKdenliveValidationError("generated Kdenlive XML requires a tractor/multitrack")

    for text in _iter_xml_strings(root):
        lowered = text.casefold()
        if any(term in lowered for term in FORBIDDEN_XML_TERMS):
            raise FKdenliveValidationError("generated Kdenlive XML contains forbidden terms")

    producer_resources: dict[str, str] = {}
    for producer in root.findall("producer"):
        producer_id = producer.attrib.get("id")
        resource = _producer_resource(producer)
        if not producer_id or resource is None:
            continue
        try:
            _ensure_safe_existing_resource(project_root, resource)
        except SecurityValidationError as exc:
            raise FKdenliveValidationError("producer resource path is unsafe") from exc
        producer_resources[producer_id] = resource

    expected_resources = {
        path
        for scene in manifest.scenes
        for path in (scene.image_path, scene.text_overlay_path)
    }
    actual_resources = set(producer_resources.values())
    if not expected_resources.issubset(actual_resources):
        raise FKdenliveValidationError("generated Kdenlive XML is missing scene resources")

    referenced_producers = {
        entry.attrib["producer"]
        for entry in root.findall(".//entry")
        if "producer" in entry.attrib
    }
    for producer_id, resource in producer_resources.items():
        if resource in expected_resources and producer_id not in referenced_producers:
            raise FKdenliveValidationError("generated Kdenlive XML has unreferenced producers")


def build_f_kdenlive_manifest(
    *,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
    e_script: EScript,
    generated_at: datetime,
) -> FKdenliveManifest:
    """Build the F manifest from validated C, D, and E artifacts."""
    slots_by_scene = {slot.scene_id: slot for slot in d_manifest.slots}
    narration_scene_ids = {line.scene_id for line in e_script.narration_script}
    scene_refs: list[dict[str, Any]] = []
    for scene in timeline.scenes:
        slot = slots_by_scene[scene.scene_id]
        scene_refs.append(
            {
                "scene_id": scene.scene_id,
                "image_slot_id": scene.image_slot_id,
                "start_sec": scene.start_sec,
                "duration_sec": scene.duration_sec,
                "start_frame": round(scene.start_sec * FPS),
                "duration_frames": round(scene.duration_sec * FPS),
                "image_path": slot.actual_image_path,
                "text_overlay_path": scene.text_overlay_path,
                "narration_script_present": scene.scene_id in narration_scene_ids,
            }
        )

    manifest = FKdenliveManifest(
        project_id=timeline.project_id,
        total_duration_sec=timeline.total_duration_sec,
        total_frames=round(timeline.total_duration_sec * FPS),
        scenes=scene_refs,
        source_artifacts=dict(SOURCE_ARTIFACTS),
        generated_at=generated_at,
        warnings=[
            "This is a local editing skeleton; manually verify in Kdenlive before export."
        ],
    )
    validate_f_kdenlive_manifest_against_inputs(
        manifest,
        timeline=timeline,
        d_manifest=d_manifest,
        e_script=e_script,
    )
    return manifest


def _markdown_cell(value: str) -> str:
    return value.replace("\n", " ").replace("|", "/").strip()


def build_manual_kdenlive_editing_guide(
    *,
    project_id: str,
    manifest: FKdenliveManifest,
    e_script: EScript,
) -> str:
    """Build the local manual editing handoff guide."""
    narration_by_scene = {line.scene_id: line.script for line in e_script.narration_script}
    lines = [
        "# Manual Kdenlive Editing Guide",
        "",
        f"Project ID: `{project_id}`",
        "",
        "Generated file: `project.kdenlive`",
        "",
        "This is a local editing skeleton. No rendering was performed. No upload was "
        "performed. No TTS or voice synthesis was performed.",
        "",
        "Record or import your own voice manually. Do not use unlicensed TTS, voice, "
        "music, or audio.",
        "",
        "Use only images confirmed in `d_image_manifest.json`. Keep rights confirmation "
        "with the project, and avoid original screenshots, personal information, real "
        "names or nicknames, and unsafe community logos.",
        "",
        "Inspect visual timing manually in Kdenlive, verify all text overlays, and verify "
        "image rights before any export.",
        "",
        "Rendering/export is out of scope for the current pipeline.",
        "",
        "| scene | start | duration | image | text overlay | narration |",
        "|---|---:|---:|---|---|---|",
    ]
    for scene in manifest.scenes:
        lines.append(
            "| "
            f"{scene.scene_id} | "
            f"{scene.start_sec:.3f} | "
            f"{scene.duration_sec:.3f} | "
            f"`{scene.image_path}` | "
            f"`{scene.text_overlay_path}` | "
            f"{_markdown_cell(narration_by_scene.get(scene.scene_id, ''))} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_f_manifest_json(project_dir: Path, manifest: FKdenliveManifest) -> Path:
    """Write and re-validate the F manifest artifact."""
    path = ensure_path_under_root(project_dir, project_dir / "f_kdenlive_manifest.json")
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    FKdenliveManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    return path


def write_manual_kdenlive_editing_guide(
    project_dir: Path,
    *,
    project_id: str,
    manifest: FKdenliveManifest,
    e_script: EScript,
) -> Path:
    """Write the manual Kdenlive editing guide."""
    path = ensure_path_under_root(project_dir, project_dir / "notes" / "manual_kdenlive_editing.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_manual_kdenlive_editing_guide(
            project_id=project_id,
            manifest=manifest,
            e_script=e_script,
        ),
        encoding="utf-8",
    )
    return path


def _upsert_artifacts(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    project_dir: Path,
    paths_by_type: dict[str, Path],
    created_at: str,
) -> None:
    for artifact_type, path in paths_by_type.items():
        relative_to_project = path.relative_to(project_dir).as_posix()
        relative_path = ensure_relative_project_path(
            f"{project_id}/{relative_to_project}"
        ).as_posix()
        digest = sha256_file(path)
        existing_artifact = conn.execute(
            "SELECT id FROM artifacts WHERE project_id = ? AND artifact_type = ?",
            (project_id, artifact_type),
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
                (project_id, artifact_type, relative_path, digest, created_at),
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


def generate_f_kdenlive_project(
    project_id: str,
    *,
    db_path: Path,
    projects_root: Path,
    clock: Callable[[], datetime] | None = None,
) -> FKdenliveManifest:
    """Generate local F Kdenlive skeleton artifacts for a script-generated project."""
    conn = connect_db(db_path)
    output_paths: dict[str, Path] = {}
    snapshot: dict[Path, bytes | None] = {}
    try:
        init_db(conn)
        project_row = _load_project_row(conn, project_id)
        if project_row["status"] != REQUIRED_CURRENT_STATUS:
            raise ProjectStatusError("F Kdenlive generation requires script_generated status")
        project_dir = _resolve_project_dir(projects_root, project_row)

        source = _load_source_artifact(project_dir, project_id)
        timeline = _load_timeline(project_dir, project_id)
        d_manifest = _load_d_manifest(project_dir, project_id)
        d_manifest = validate_d_image_manifest_against_timeline(
            d_manifest,
            timeline,
            project_root=project_dir,
            require_ready_for_e=True,
        )
        e_script = _load_e_script(project_dir)
        validate_e_script_against_inputs(
            e_script,
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
        )
        manifest = build_f_kdenlive_manifest(
            timeline=timeline,
            d_manifest=d_manifest,
            e_script=e_script,
            generated_at=_now_kst(clock),
        )

        planned_paths = [
            ensure_path_under_root(project_dir, project_dir / relative_path)
            for relative_path in F_ARTIFACTS.values()
        ]
        snapshot = _snapshot_files(planned_paths)

        conn.execute("BEGIN")
        current_row = _load_project_row(conn, project_id)
        if current_row["status"] != REQUIRED_CURRENT_STATUS:
            raise ProjectStatusError("project status changed before F persistence")

        kdenlive_path = ensure_path_under_root(project_dir, project_dir / "project.kdenlive")
        write_kdenlive_project_xml(kdenlive_path, manifest)
        validate_generated_kdenlive_xml(
            kdenlive_path,
            project_root=project_dir,
            manifest=manifest,
        )
        manifest_path = write_f_manifest_json(project_dir, manifest)
        guide_path = write_manual_kdenlive_editing_guide(
            project_dir,
            project_id=project_id,
            manifest=manifest,
            e_script=e_script,
        )
        output_paths = {
            "kdenlive_project": kdenlive_path,
            "f_kdenlive_manifest": manifest_path,
            "manual_kdenlive_editing_guide": guide_path,
        }
        _upsert_artifacts(
            conn,
            project_id=project_id,
            project_dir=project_dir,
            paths_by_type=output_paths,
            created_at=_now_kst(clock).isoformat(),
        )
        conn.commit()
        return manifest
    except Exception:
        conn.rollback()
        if snapshot:
            _restore_files(snapshot)
        else:
            for path in output_paths.values():
                if path.exists():
                    path.unlink()
        raise
    finally:
        conn.close()
