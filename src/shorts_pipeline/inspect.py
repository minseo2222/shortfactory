"""Read-only local project inspection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from shorts_pipeline.db import connect_readonly_db
from shorts_pipeline.models import (
    ArtifactInspectionRow,
    ProjectInspectionResult,
    ProjectInspectionSummary,
    ProjectStatusEvent,
)
from shorts_pipeline.security import (
    SecurityValidationError,
    ensure_path_under_root,
    ensure_relative_project_path,
    sha256_file,
)


class ProjectInspectionError(ValueError):
    """Raised when read-only project inspection cannot be completed."""


class ProjectNotFoundError(ProjectInspectionError):
    """Raised when the requested project row does not exist."""


def _load_project_row(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT id, project_dir, status, created_at, updated_at
        FROM projects
        WHERE id = ?
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        raise ProjectNotFoundError(f"project not found: {project_id}")
    return row


def _load_status_events(conn: sqlite3.Connection, project_id: str) -> list[ProjectStatusEvent]:
    rows = conn.execute(
        """
        SELECT project_id, from_status, to_status, stage, reason, created_at
        FROM project_status_events
        WHERE project_id = ?
        ORDER BY id
        """,
        (project_id,),
    ).fetchall()
    return [ProjectStatusEvent.model_validate(dict(row)) for row in rows]


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


def _inspect_artifact_row(
    row: sqlite3.Row,
    *,
    projects_root: Path,
    verify_files: bool,
    verify_hashes: bool,
) -> ArtifactInspectionRow:
    relative_path = row["relative_path"]
    raw_sha256 = row["sha256"] or None
    exists: bool | None = None
    sha256_matches: bool | None = None
    verification_error: str | None = None
    path_is_safe = True

    try:
        safe_relative_path = ensure_relative_project_path(relative_path)
        artifact_path = ensure_path_under_root(projects_root, projects_root / safe_relative_path)
    except SecurityValidationError as exc:
        path_is_safe = False
        verification_error = f"unsafe path: {exc}"
    else:
        if verify_files:
            if not artifact_path.exists():
                exists = False
                verification_error = "artifact file is missing"
            elif not artifact_path.is_file():
                exists = False
                verification_error = "artifact path is not a file"
            else:
                exists = True
                if verify_hashes and raw_sha256:
                    try:
                        sha256_matches = sha256_file(artifact_path) == raw_sha256
                    except OSError as exc:
                        sha256_matches = False
                        verification_error = f"hash verification failed: {exc}"
                    else:
                        if not sha256_matches:
                            verification_error = "sha256 mismatch"

    return ArtifactInspectionRow(
        artifact_id=row["id"],
        project_id=row["project_id"],
        artifact_type=row["artifact_type"],
        relative_path=relative_path,
        sha256=raw_sha256,
        created_at=row["created_at"],
        exists=exists,
        path_is_safe=path_is_safe,
        sha256_matches=sha256_matches,
        verification_error=verification_error,
    )


def _has_artifact_problem(row: ArtifactInspectionRow) -> bool:
    return (
        not row.path_is_safe
        or row.exists is False
        or row.sha256_matches is False
        or row.verification_error is not None
    )


def inspect_project(
    *,
    db_path: Path,
    projects_root: Path,
    project_id: str,
    verify_files: bool = True,
    verify_hashes: bool = True,
) -> ProjectInspectionResult:
    """Inspect one existing local project without mutating DB or files."""
    if not project_id:
        raise ProjectInspectionError("project_id is required")

    resolved_db_path = Path(db_path).expanduser().resolve()
    resolved_projects_root = Path(projects_root).expanduser().resolve()
    if not resolved_db_path.is_file():
        raise ProjectInspectionError(f"database file does not exist: {resolved_db_path}")
    if not resolved_projects_root.is_dir():
        raise ProjectInspectionError(f"projects root does not exist: {resolved_projects_root}")

    effective_verify_hashes = verify_hashes and verify_files
    conn = connect_readonly_db(resolved_db_path)
    try:
        project_row = _load_project_row(conn, project_id)
        status_events = _load_status_events(conn, project_id)
        artifact_rows = [
            _inspect_artifact_row(
                row,
                projects_root=resolved_projects_root,
                verify_files=verify_files,
                verify_hashes=effective_verify_hashes,
            )
            for row in _load_artifact_rows(conn, project_id)
        ]
    finally:
        conn.close()

    warnings: list[str] = []
    if not status_events:
        warnings.append("no status events found")
    if not artifact_rows:
        warnings.append("no artifact rows found")

    return ProjectInspectionResult(
        project=ProjectInspectionSummary(
            project_id=project_row["id"],
            status=project_row["status"],
            project_dir=project_row["project_dir"] or None,
            created_at=project_row["created_at"],
            updated_at=project_row["updated_at"],
        ),
        status_sequence=[event.to_status for event in status_events],
        status_events=status_events,
        artifacts=artifact_rows,
        artifact_problem_count=sum(1 for row in artifact_rows if _has_artifact_problem(row)),
        warnings=warnings,
    )
