"""Phase 2 B scene-plan generation service."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from shorts_pipeline.config import KST
from shorts_pipeline.db import connect_db, init_db, insert_project_status_event
from shorts_pipeline.llm.b_provider import BScenePlanProvider
from shorts_pipeline.models import BScenePlan, SourceArtifact
from shorts_pipeline.security import (
    ensure_path_under_root,
    ensure_relative_project_path,
    sha256_file,
)
from shorts_pipeline.state_machine import assert_transition_allowed

DEFAULT_B_PROMPT_VERSION = "b_scene_plan_prompt.v2.1.001"
B_SCHEMA_VERSION = "b_scene_plan.v2.1"
PLANNED_STATUS = "planned"
REQUIRED_CURRENT_STATUS = "candidate_selected"

SAFETY_GUARD_TERMS = (
    "실명",
    "닉네임",
    "개인정보",
    "범죄 단정",
    "허위 수치",
    "원문 직접 인용",
)
FORBIDDEN_RAW_SOURCE_TERMS = (
    "full_text",
    "raw_html",
    "comments",
    "screenshot",
    "api_key",
    "secret",
)


class ProviderNotConfiguredError(ValueError):
    """Raised when B generation is requested without an injected provider."""


class ProjectNotFoundError(ValueError):
    """Raised when a project row does not exist."""


class ProjectStatusError(ValueError):
    """Raised when the project is not in the required status."""


class BScenePlanValidationError(ValueError):
    """Raised when a parsed B scene plan fails application-level validation."""


class BScenePlanGenerationError(ValueError):
    """Raised when all provider attempts fail validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        joined = "; ".join(errors)
        super().__init__(f"B scene plan generation failed validation: {joined}")


def _now_kst(clock: Callable[[], datetime] | None = None) -> datetime:
    current = clock() if clock else datetime.now(tz=KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).replace(microsecond=0)


def _normalize_for_copy_check(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _expected_scene_ids(count: int) -> list[str]:
    return [f"s{index:02d}" for index in range(1, count + 1)]


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


def _summarize_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ")
    return text[:500]


def validate_b_scene_plan_against_source(
    plan: BScenePlan,
    source: SourceArtifact,
) -> None:
    """Apply deterministic B validation rules beyond Pydantic field checks."""
    if plan.schema_version != B_SCHEMA_VERSION:
        raise BScenePlanValidationError("schema_version must be b_scene_plan.v2.1")

    actual_scene_ids = [scene.scene_id for scene in plan.scene_plan]
    expected_scene_ids = _expected_scene_ids(len(plan.scene_plan))
    if actual_scene_ids != expected_scene_ids:
        raise BScenePlanValidationError("scene_id values must be consecutive from s01")
    if len(actual_scene_ids) != len(set(actual_scene_ids)):
        raise BScenePlanValidationError("scene_id values must not contain duplicates")

    total_duration = sum(scene.duration_sec for scene in plan.scene_plan)
    if abs(total_duration - plan.target_duration_sec) > 5.0:
        raise BScenePlanValidationError("scene durations must stay within target +/- 5 seconds")

    metadata_strings = [
        source.source_title,
        source.user_or_llm_summary,
        source.hook,
        source.why_shortable,
    ]
    normalized_metadata = [_normalize_for_copy_check(text) for text in metadata_strings]

    for scene in plan.scene_plan:
        if not scene.source_basis:
            raise BScenePlanValidationError(f"{scene.scene_id} requires source_basis")
        if not scene.do_not_say:
            raise BScenePlanValidationError(f"{scene.scene_id} requires do_not_say")
        if not any(
            guard in item for item in scene.do_not_say for guard in SAFETY_GUARD_TERMS
        ):
            raise BScenePlanValidationError(f"{scene.scene_id} requires a safety guard")

        screen_text = _normalize_for_copy_check(scene.screen_text)
        if len(screen_text) >= 12 and any(screen_text in meta for meta in normalized_metadata):
            raise BScenePlanValidationError(
                f"{scene.scene_id} screen_text looks copied from stored source metadata"
            )

    for text in _iter_keys_and_strings(plan.model_dump(mode="json")):
        lowered = text.casefold()
        if any(term in lowered for term in FORBIDDEN_RAW_SOURCE_TERMS):
            raise BScenePlanValidationError("B scene plan contains forbidden raw-source terms")


def _load_project_row(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ProjectNotFoundError(f"project not found: {project_id}")
    return row


def _load_source_artifact(
    *,
    projects_root: Path,
    project_row: sqlite3.Row,
) -> tuple[SourceArtifact, Path]:
    relative_project_dir = ensure_relative_project_path(project_row["project_dir"])
    root = Path(projects_root).resolve()
    project_dir = ensure_path_under_root(root, root / relative_project_dir)
    source_path = ensure_path_under_root(project_dir, project_dir / "source.json")

    source_data = json.loads(source_path.read_text(encoding="utf-8"))
    source = SourceArtifact.model_validate(source_data)
    if source.project_id != project_row["id"]:
        raise ValueError("source.json project_id does not match project row")
    return source, project_dir


def _parse_and_validate_provider_payload(
    payload: dict[str, Any],
    *,
    source: SourceArtifact,
) -> BScenePlan:
    plan = BScenePlan.model_validate(payload)
    validate_b_scene_plan_against_source(plan, source)
    return plan


def _validate_with_retries(
    *,
    source: SourceArtifact,
    provider: BScenePlanProvider,
    prompt_version: str,
    max_retries: int,
) -> BScenePlan:
    previous_errors: list[str] = []
    total_attempts = max_retries + 1
    for _attempt in range(total_attempts):
        payload = provider.generate(
            source=source,
            prompt_version=prompt_version,
            previous_errors=list(previous_errors),
        )
        try:
            return _parse_and_validate_provider_payload(payload, source=source)
        except (ValidationError, BScenePlanValidationError) as exc:
            previous_errors.append(_summarize_error(exc))

    raise BScenePlanGenerationError(previous_errors)


def write_b_scene_plan_json(project_dir: str | Path, plan: BScenePlan) -> Path:
    """Write and re-validate the B scene-plan artifact."""
    root = Path(project_dir).resolve()
    output_path = ensure_path_under_root(root, root / "b_scene_plan.json")
    if output_path.exists():
        raise FileExistsError(f"B scene plan already exists: {output_path}")

    data = plan.model_dump(mode="json")
    try:
        output_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        loaded = json.loads(output_path.read_text(encoding="utf-8"))
        BScenePlan.model_validate(loaded)
    except Exception:
        if output_path.exists():
            output_path.unlink()
        raise
    return output_path


def generate_b_scene_plan(
    project_id: str,
    *,
    db_path: Path,
    projects_root: Path,
    provider: BScenePlanProvider | None = None,
    clock: Callable[[], datetime] | None = None,
    prompt_version: str = DEFAULT_B_PROMPT_VERSION,
    max_retries: int = 2,
) -> BScenePlan:
    """Generate, validate, persist, and mark a B scene plan as planned."""
    if provider is None:
        raise ProviderNotConfiguredError("B scene plan provider must be injected")
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")

    conn = connect_db(db_path)
    output_path: Path | None = None
    try:
        init_db(conn)
        project_row = _load_project_row(conn, project_id)
        if project_row["status"] != REQUIRED_CURRENT_STATUS:
            raise ProjectStatusError("B generation requires candidate_selected status")

        source, project_dir = _load_source_artifact(
            projects_root=projects_root,
            project_row=project_row,
        )
        plan = _validate_with_retries(
            source=source,
            provider=provider,
            prompt_version=prompt_version,
            max_retries=max_retries,
        )

        created_at = _now_kst(clock).isoformat()
        artifact_relative_path = ensure_relative_project_path(
            f"{project_id}/b_scene_plan.json"
        ).as_posix()

        conn.execute("BEGIN")
        current_row = _load_project_row(conn, project_id)
        if current_row["status"] != REQUIRED_CURRENT_STATUS:
            raise ProjectStatusError("project status changed before B persistence")
        assert_transition_allowed(current_row["status"], PLANNED_STATUS)

        output_path = write_b_scene_plan_json(project_dir, plan)
        digest = sha256_file(output_path)
        scene_plan_json = json.dumps(
            plan.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )

        llm_cursor = conn.execute(
            """
            INSERT INTO llm_runs (
                project_id,
                stage,
                provider,
                model_name,
                prompt_version,
                schema_version,
                status,
                error_code,
                input_tokens,
                output_tokens,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                "B",
                getattr(provider, "provider_name", "fake"),
                getattr(provider, "model_name", "mock-b-scene-plan-v2.1"),
                prompt_version,
                B_SCHEMA_VERSION,
                "succeeded",
                None,
                None,
                None,
                created_at,
            ),
        )
        llm_run_id = llm_cursor.lastrowid

        conn.execute(
            """
            INSERT INTO plans (
                project_id,
                schema_version,
                scene_plan_json,
                artifact_path,
                llm_run_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                B_SCHEMA_VERSION,
                scene_plan_json,
                artifact_relative_path,
                llm_run_id,
                created_at,
            ),
        )
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
            (
                project_id,
                "b_scene_plan",
                artifact_relative_path,
                digest,
                created_at,
            ),
        )
        conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (PLANNED_STATUS, created_at, project_id),
        )
        insert_project_status_event(
            conn,
            project_id=project_id,
            from_status=current_row["status"],
            to_status=PLANNED_STATUS,
            stage="B",
            reason="scene_plan_generated",
            created_at=created_at,
        )
        conn.commit()
        return plan
    except Exception:
        conn.rollback()
        if output_path is not None and output_path.exists():
            output_path.unlink()
        raise
    finally:
        conn.close()
