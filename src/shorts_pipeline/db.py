"""SQLite schema helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from shorts_pipeline.models import ProjectStatusEvent
from shorts_pipeline.state_machine import PROJECT_STATUSES


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    if column_name not in _column_names(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def connect_db(path: Path | str) -> sqlite3.Connection:
    """Connect to SQLite with foreign keys enabled and WAL requested."""
    db_path = Path(path)
    if str(path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    # Wait for a write lock instead of failing immediately, so concurrent
    # project creations (which use BEGIN IMMEDIATE) serialize rather than race.
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def connect_readonly_db(path: Path | str) -> sqlite3.Connection:
    """Open an existing SQLite database in read-only mode."""
    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"database file does not exist: {db_path}")

    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the v2.1 first-run schema if it does not already exist."""
    status_values = ", ".join(f"'{status}'" for status in PROJECT_STATUSES)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            project_dir TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL,
            source_title TEXT NOT NULL,
            community TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({status_values})),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (project_dir NOT LIKE '../%'),
            CHECK (project_dir NOT LIKE '%/../%'),
            CHECK (project_dir NOT LIKE '/%'),
            CHECK (project_dir NOT LIKE 'http://%'),
            CHECK (project_dir NOT LIKE 'https://%')
        );

        CREATE TABLE IF NOT EXISTS llm_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            stage TEXT NOT NULL,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL DEFAULT '',
            schema_version TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            error_code TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            schema_version TEXT NOT NULL,
            scene_plan_json TEXT NOT NULL DEFAULT '{{}}',
            artifact_path TEXT NOT NULL,
            llm_run_id INTEGER REFERENCES llm_runs(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS timelines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            schema_version TEXT NOT NULL,
            timeline_json TEXT NOT NULL DEFAULT '{{}}',
            total_duration_sec REAL NOT NULL DEFAULT 0,
            artifact_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            sha256 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            CHECK (relative_path NOT LIKE '../%'),
            CHECK (relative_path NOT LIKE '%/../%'),
            CHECK (relative_path NOT LIKE '/%'),
            CHECK (relative_path NOT LIKE 'http://%'),
            CHECK (relative_path NOT LIKE 'https://%')
        );

        CREATE TABLE IF NOT EXISTS image_manifests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            schema_version TEXT NOT NULL,
            manifest_json TEXT NOT NULL DEFAULT '{{}}',
            artifact_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            schema_version TEXT NOT NULL,
            llm_run_id INTEGER REFERENCES llm_runs(id) ON DELETE SET NULL,
            narration_json TEXT NOT NULL DEFAULT '[]',
            title_candidates_json TEXT NOT NULL DEFAULT '[]',
            recommended_title TEXT NOT NULL DEFAULT '',
            artifact_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_status_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            from_status TEXT,
            to_status TEXT NOT NULL,
            stage TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    _ensure_column(conn, "projects", "project_dir", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "llm_runs", "prompt_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "llm_runs", "schema_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "llm_runs", "input_tokens", "INTEGER")
    _ensure_column(conn, "llm_runs", "output_tokens", "INTEGER")
    _ensure_column(conn, "plans", "scene_plan_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "plans", "llm_run_id", "INTEGER")
    _ensure_column(conn, "timelines", "timeline_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "timelines", "total_duration_sec", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "image_manifests", "manifest_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "artifacts", "sha256", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "scripts", "llm_run_id", "INTEGER")
    _ensure_column(conn, "scripts", "narration_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "scripts", "title_candidates_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "scripts", "recommended_title", "TEXT NOT NULL DEFAULT ''")
    conn.commit()


def insert_project_status_event(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    from_status: str | None,
    to_status: str,
    stage: str,
    reason: str,
    created_at: str,
) -> None:
    """Append one project status history event inside the caller's transaction."""
    conn.execute(
        """
        INSERT INTO project_status_events (
            project_id,
            from_status,
            to_status,
            stage,
            reason,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, from_status, to_status, stage, reason, created_at),
    )


def list_project_status_events(
    conn_or_db_path: sqlite3.Connection | Path | str,
    project_id: str,
) -> list[ProjectStatusEvent]:
    """Return status events for a project in append order."""
    owns_connection = not isinstance(conn_or_db_path, sqlite3.Connection)
    conn = connect_db(conn_or_db_path) if owns_connection else conn_or_db_path
    try:
        init_db(conn)
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
    finally:
        if owns_connection:
            conn.close()
