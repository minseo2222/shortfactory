"""Local project creation service for manually selected candidates."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from shorts_pipeline.config import KST
from shorts_pipeline.db import connect_db, init_db, insert_project_status_event
from shorts_pipeline.models import CandidateCard, Project, SourceArtifact
from shorts_pipeline.security import (
    SecurityValidationError,
    ensure_path_under_root,
    ensure_relative_project_path,
)

PROJECT_ID_RE = re.compile(r"^PRJ_\d{8}_\d{4}$")
INITIAL_PROJECT_STATUS = "candidate_selected"

PROJECT_DIRECTORIES = (
    "assets/placeholders",
    "assets/user_images",
    "assets/text_overlays",
    "assets/bgm",
    "notes",
    "exports",
    "logs",
)

PROJECT_TEXT_FILES = {
    "assets/bgm/README.md": (
        "# BGM\n\n"
        "Place user-approved local background music files here in a later phase.\n"
        "Do not store downloaded or rights-unclear media by default.\n"
    ),
    "notes/replace_images.md": (
        "# Replace Images\n\n"
        "Replace files in `assets/user_images/` manually, or replace clips manually in Kdenlive.\n"
    ),
    "notes/recording_guide.md": (
        "# Recording Guide\n\n"
        "Record narration manually after `e_script.json` is generated in a later phase.\n"
    ),
    "notes/source_policy.md": (
        "# Source Policy\n\n"
        "This project stores only minimal source metadata and a user-written summary.\n"
        "Do not store full source posts, comments, raw HTML, screenshots, or secrets.\n"
    ),
    "exports/README.md": (
        "# Exports\n\n"
        "Final rendered media may be placed here manually in a later phase.\n"
    ),
}


def _now_kst(clock: Callable[[], datetime] | None = None) -> datetime:
    current = clock() if clock else datetime.now(tz=KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).replace(microsecond=0)


def _coerce_candidate(candidate: CandidateCard | Mapping[str, Any]) -> CandidateCard:
    validated = (
        candidate if isinstance(candidate, CandidateCard) else CandidateCard.model_validate(candidate)
    )
    if validated.status == "rejected_in_session":
        raise ValueError("rejected session candidates cannot create projects")
    return validated


def allocate_project_id(conn: sqlite3.Connection, created_at: datetime) -> str:
    """Allocate the next human-readable project ID for the KST date."""
    date_slug = created_at.astimezone(KST).strftime("%Y%m%d")
    prefix = f"PRJ_{date_slug}_"
    rows = conn.execute(
        "SELECT id FROM projects WHERE id LIKE ? ORDER BY id DESC",
        (f"{prefix}%",),
    ).fetchall()
    max_sequence = 0
    for row in rows:
        project_id = row["id"]
        if PROJECT_ID_RE.fullmatch(project_id):
            max_sequence = max(max_sequence, int(project_id.rsplit("_", 1)[1]))
    return f"{prefix}{max_sequence + 1:04d}"


def create_project_folder(projects_root: str | Path, project_id: str) -> Path:
    """Create the Phase 1 project directory tree under `projects_root`."""
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise SecurityValidationError("invalid generated project id")

    relative_project_dir = ensure_relative_project_path(project_id)
    root = Path(projects_root).resolve()
    project_dir = ensure_path_under_root(root, root / relative_project_dir)

    root.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=False, exist_ok=False)

    for directory in PROJECT_DIRECTORIES:
        target_dir = ensure_path_under_root(project_dir, project_dir / directory)
        target_dir.mkdir(parents=True, exist_ok=False)

    for relative_path, content in PROJECT_TEXT_FILES.items():
        target_file = ensure_path_under_root(project_dir, project_dir / relative_path)
        target_file.write_text(content, encoding="utf-8")

    return project_dir


def build_source_artifact(
    candidate: CandidateCard,
    *,
    project_id: str,
    created_at: str,
) -> SourceArtifact:
    """Build the minimal persisted source artifact from an ephemeral candidate."""
    return SourceArtifact(
        project_id=project_id,
        source_url=candidate.source_url,
        source_community=candidate.community,
        source_title=candidate.title,
        user_or_llm_summary=candidate.summary,
        hook=candidate.hook,
        why_shortable=candidate.why_shortable,
        risk_flags_for_user=list(candidate.risk_flags_for_user),
        created_at=created_at,
    )


def write_source_json(project_dir: str | Path, source_artifact: SourceArtifact) -> Path:
    """Write and re-validate the minimal `source.json` artifact."""
    root = Path(project_dir).resolve()
    source_path = ensure_path_under_root(root, root / "source.json")
    data = source_artifact.model_dump(mode="json")
    source_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    loaded = json.loads(source_path.read_text(encoding="utf-8"))
    SourceArtifact.model_validate(loaded)
    return source_path


def create_project_from_candidate(
    candidate: CandidateCard | Mapping[str, Any],
    *,
    db_path: Path,
    projects_root: Path,
    clock: Callable[[], datetime] | None = None,
) -> Project:
    """Create one local selected project from one manually entered candidate."""
    validated_candidate = _coerce_candidate(candidate)
    created_dt = _now_kst(clock)
    created_at = created_dt.isoformat()

    project_dir: Path | None = None
    conn = connect_db(db_path)
    try:
        init_db(conn)
        conn.execute("BEGIN")
        project_id = allocate_project_id(conn, created_dt)
        conn.execute(
            """
            INSERT INTO projects (
                id,
                project_dir,
                source_url,
                source_title,
                community,
                status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                project_id,
                str(validated_candidate.source_url),
                validated_candidate.title,
                validated_candidate.community,
                INITIAL_PROJECT_STATUS,
                created_at,
                created_at,
            ),
        )
        insert_project_status_event(
            conn,
            project_id=project_id,
            from_status=None,
            to_status=INITIAL_PROJECT_STATUS,
            stage="A",
            reason="project_created",
            created_at=created_at,
        )

        project_dir = create_project_folder(projects_root, project_id)
        source_artifact = build_source_artifact(
            validated_candidate,
            project_id=project_id,
            created_at=created_at,
        )
        source_json_path = write_source_json(project_dir, source_artifact)

        conn.commit()
        return Project(
            project_id=project_id,
            status=INITIAL_PROJECT_STATUS,
            project_dir=str(project_dir),
            source_json_path=str(source_json_path),
            created_at=created_at,
        )
    except Exception:
        conn.rollback()
        if project_dir is not None and project_dir.exists():
            shutil.rmtree(project_dir)
        raise
    finally:
        conn.close()
