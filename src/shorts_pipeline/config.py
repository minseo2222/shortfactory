"""Configuration and time helpers for the local pipeline."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
PROJECT_ROOT_ENV = "SHORTS_PIPELINE_PROJECT_ROOT"
DB_PATH_ENV = "SHORTS_PIPELINE_DB_PATH"


def now_kst_iso(clock: Callable[[], datetime] | None = None) -> str:
    """Return the current time in KST as an ISO-8601 string."""
    current = clock() if clock else datetime.now(tz=KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).replace(microsecond=0).isoformat()


def get_project_root() -> Path:
    """Return the configured local project root."""
    return Path(os.getenv(PROJECT_ROOT_ENV, "projects"))


def get_db_path() -> Path:
    """Return the configured SQLite DB path."""
    return Path(os.getenv(DB_PATH_ENV, "projects/shorts_pipeline.sqlite3"))


@dataclass(frozen=True)
class Settings:
    """Minimal runtime settings without exposing secret values."""

    project_root: Path
    db_path: Path
    kdenlive_min_version: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            project_root=get_project_root(),
            db_path=get_db_path(),
            kdenlive_min_version=os.getenv(
                "SHORTS_PIPELINE_KDENLIVE_MIN_VERSION",
                "26.04.1",
            ),
        )
