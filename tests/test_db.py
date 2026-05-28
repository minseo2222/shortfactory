from __future__ import annotations

import sqlite3

import pytest

from shorts_pipeline.config import now_kst_iso
from shorts_pipeline.db import connect_db, init_db


def test_sqlite_schema_init_smoke(tmp_path) -> None:
    conn = connect_db(tmp_path / "shorts.sqlite3")
    init_db(conn)

    foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    assert foreign_keys == 1
    assert journal_mode in {"wal", "delete", "memory"}
    assert "projects" in tables
    assert "artifacts" in tables


def test_invalid_project_status_rejected_by_check_constraint(tmp_path) -> None:
    conn = connect_db(tmp_path / "shorts.sqlite3")
    init_db(conn)
    now = now_kst_iso()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO projects (
                id, source_url, source_title, community, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PRJ_TEST",
                "https://example.com/post/1",
                "Example",
                "example",
                "invalid_status",
                now,
                now,
            ),
        )
