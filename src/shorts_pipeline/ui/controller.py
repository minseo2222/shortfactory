"""Streamlit-free orchestration layer for the local A->F pipeline UI.

This module imports no UI framework. It only composes the existing phase
services so the UI stays a thin rendering layer and the orchestration is unit
testable. It performs no network egress: B/E default to the deterministic fake
providers, and a real provider is used only when the explicit opt-in is set.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from shorts_pipeline.b_service import generate_b_scene_plan
from shorts_pipeline.c_service import compile_c_project
from shorts_pipeline.d_service import confirm_d_image_manifest, initialize_d_image_manifest
from shorts_pipeline.db import connect_readonly_db, list_project_status_events
from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider
from shorts_pipeline.e_service import generate_e_script
from shorts_pipeline.f_service import generate_f_kdenlive_project
from shorts_pipeline.llm.real_providers import (
    real_llm_enabled,
    resolve_b_provider,
    resolve_e_provider,
    selected_backend,
)
from shorts_pipeline.models import (
    BScenePlan,
    DImageManifest,
    FKdenliveManifest,
    Project,
    ProjectStatusEvent,
    TimelineJson,
)
from shorts_pipeline.project_service import create_project_from_candidate

Clock = Callable[[], datetime] | None


@dataclass(frozen=True)
class PipelineConfig:
    """Local storage locations for one UI session."""

    db_path: Path
    projects_root: Path

    @classmethod
    def from_base_dir(cls, base_dir: str | Path) -> "PipelineConfig":
        base = Path(base_dir)
        return cls(
            db_path=base / "shorts_pipeline.sqlite3",
            projects_root=base / "projects",
        )


# --- Provider selection (default fake, opt-in real) -------------------------


def provider_mode() -> str:
    """Return a short human-readable label for the active provider mode."""
    backend = selected_backend()
    if real_llm_enabled() and backend:
        return f"real:{backend}"
    return "fake"


def select_b_provider():
    """Return the opted-in real B provider, otherwise the deterministic fake."""
    return resolve_b_provider() or DevFakeBProvider()


def select_e_provider():
    """Return the opted-in real E provider, otherwise the deterministic fake."""
    return resolve_e_provider() or DevFakeEProvider()


# --- Stage wrappers ---------------------------------------------------------


def create_project(
    config: PipelineConfig,
    candidate: Mapping[str, Any],
    *,
    clock: Clock = None,
) -> Project:
    return create_project_from_candidate(
        candidate, db_path=config.db_path, projects_root=config.projects_root, clock=clock
    )


def run_b(
    config: PipelineConfig, project_id: str, *, provider=None, clock: Clock = None
) -> BScenePlan:
    return generate_b_scene_plan(
        project_id,
        db_path=config.db_path,
        projects_root=config.projects_root,
        provider=provider if provider is not None else select_b_provider(),
        clock=clock,
    )


def run_c(config: PipelineConfig, project_id: str, *, clock: Clock = None) -> TimelineJson:
    return compile_c_project(
        project_id, db_path=config.db_path, projects_root=config.projects_root, clock=clock
    )


def init_d(config: PipelineConfig, project_id: str, *, clock: Clock = None) -> DImageManifest:
    return initialize_d_image_manifest(
        project_id, db_path=config.db_path, projects_root=config.projects_root, clock=clock
    )


def confirm_d(
    config: PipelineConfig,
    project_id: str,
    payload: Mapping[str, Any] | DImageManifest,
    *,
    clock: Clock = None,
) -> DImageManifest:
    return confirm_d_image_manifest(
        project_id,
        payload,
        db_path=config.db_path,
        projects_root=config.projects_root,
        clock=clock,
    )


def run_e(config: PipelineConfig, project_id: str, *, provider=None, clock: Clock = None):
    return generate_e_script(
        project_id,
        db_path=config.db_path,
        projects_root=config.projects_root,
        provider=provider if provider is not None else select_e_provider(),
        clock=clock,
    )


def run_f(config: PipelineConfig, project_id: str, *, clock: Clock = None) -> FKdenliveManifest:
    return generate_f_kdenlive_project(
        project_id, db_path=config.db_path, projects_root=config.projects_root, clock=clock
    )


# --- Read helpers -----------------------------------------------------------


def current_status(config: PipelineConfig, project_id: str) -> str | None:
    """Return the persisted project status, or None when the project is absent."""
    if not Path(config.db_path).exists():
        return None
    conn = connect_readonly_db(config.db_path)
    try:
        row = conn.execute("SELECT status FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        return row[0]
    finally:
        conn.close()


def status_events(config: PipelineConfig, project_id: str) -> list[ProjectStatusEvent]:
    return list_project_status_events(config.db_path, project_id)


# --- D image manifest payload construction ----------------------------------


def build_ready_d_payload(
    timeline: TimelineJson,
    *,
    slot_inputs: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a confirm-ready D manifest payload from the timeline.

    Each slot defaults to using the C-generated user-image slot file as the
    actual image, marked replaced with rights confirmed and all unsafe flags
    cleared. ``slot_inputs`` may override per-scene fields (keyed by scene_id),
    which is how the UI collects the user's rights confirmation and notes.
    """
    slot_inputs = slot_inputs or {}
    slots: list[dict[str, Any]] = []
    for scene in timeline.scenes:
        slot: dict[str, Any] = {
            "slot_id": scene.image_slot_id,
            "scene_id": scene.scene_id,
            "status": "replaced",
            "planned_image_path": scene.image_path,
            "actual_image_path": scene.image_path,
            "actual_image_note": f"User-owned safe image for {scene.scene_id}.",
            "source_type": "user_owned",
            "rights_confirmed_by_user": True,
            "contains_face": False,
            "face_rights_confirmed": None,
            "contains_personal_info": False,
            "contains_original_capture": False,
            "contains_community_logo": False,
            "image_sha256": None,
        }
        slot.update(slot_inputs.get(scene.scene_id, {}))
        slots.append(slot)
    return {
        "schema_version": "d_image_manifest.v2.1",
        "project_id": timeline.project_id,
        "image_insert_completed": True,
        "user_confirmed": True,
        "completed_at": None,
        "slots": slots,
        "warnings": [],
    }


def run_full_pipeline(
    config: PipelineConfig,
    candidate: Mapping[str, Any],
    *,
    slot_inputs: Mapping[str, Mapping[str, Any]] | None = None,
    clock: Clock = None,
) -> dict[str, Any]:
    """Run A->F end to end with the selected providers.

    Returns the key artifacts. Used by the UI's one-click path and by tests.
    """
    project = create_project(config, candidate, clock=clock)
    run_b(config, project.project_id, clock=clock)
    timeline = run_c(config, project.project_id, clock=clock)
    init_d(config, project.project_id, clock=clock)
    confirm_d(
        config,
        project.project_id,
        build_ready_d_payload(timeline, slot_inputs=slot_inputs),
        clock=clock,
    )
    script = run_e(config, project.project_id, clock=clock)
    manifest = run_f(config, project.project_id, clock=clock)
    return {
        "project_id": project.project_id,
        "timeline": timeline,
        "script": script,
        "f_manifest": manifest,
        "status": current_status(config, project.project_id),
    }


def run_pipeline(
    config: PipelineConfig,
    candidate: Mapping[str, Any],
    *,
    b_provider,
    e_provider,
    accept_placeholders: bool,
    clock: Clock = None,
) -> dict[str, Any]:
    """Run the pipeline with explicit providers for a CLI/automation entry point.

    Always runs A -> B -> C. When ``accept_placeholders`` is True the D image
    manifest is auto-confirmed from the generated placeholder slots (a dry-run
    handoff; the user still replaces images before real use) and E -> F run to
    completion. When False, the run stops at the D human image/rights gate.
    """
    project = create_project(config, candidate, clock=clock)
    project_id = project.project_id
    run_b(config, project_id, provider=b_provider, clock=clock)
    timeline = run_c(config, project_id, clock=clock)

    if not accept_placeholders:
        return {
            "project_id": project_id,
            "status": current_status(config, project_id),
            "completed": False,
            "stopped_at": "D (manual image insertion and rights confirmation)",
        }

    init_d(config, project_id, clock=clock)
    confirm_d(config, project_id, build_ready_d_payload(timeline), clock=clock)
    run_e(config, project_id, provider=e_provider, clock=clock)
    run_f(config, project_id, clock=clock)
    return {
        "project_id": project_id,
        "status": current_status(config, project_id),
        "completed": True,
        "stopped_at": None,
    }
