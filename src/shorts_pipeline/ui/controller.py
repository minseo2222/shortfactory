"""Streamlit-free orchestration layer for the local A->F pipeline UI.

This module imports no UI framework. It only composes the existing phase
services so the UI stays a thin rendering layer and the orchestration is unit
testable. It performs no network egress: B/E default to the deterministic fake
providers, and a real provider is used only when the explicit opt-in is set.
"""

from __future__ import annotations

import hashlib
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
    provider_readiness,
    resolve_b_provider,
    resolve_e_provider,
)
from shorts_pipeline.models import (
    BScenePlan,
    DImageManifest,
    EScript,
    FKdenliveManifest,
    Project,
    ProjectStatusEvent,
    SourceArtifact,
    TimelineJson,
)
from shorts_pipeline.project_service import create_project_from_candidate
from shorts_pipeline.security import (
    ensure_path_under_root,
    ensure_relative_project_path,
    validate_media_extension,
)
from shorts_pipeline.sources import (
    DiscoveredCandidate,
    NaverSearchSourceProvider,
    RssSourceProvider,
    SingleLinkFetchProvider,
    SourceError,
    YouTubeSourceProvider,
)

Clock = Callable[[], datetime] | None

MAX_USER_IMAGE_BYTES = 20 * 1024 * 1024


class UserImageError(ValueError):
    """Raised when an uploaded user image fails local safety validation."""


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
    return provider_readiness()["mode"]


def readiness() -> dict:
    """Secret-free real-LLM readiness summary for the UI provider panel."""
    return provider_readiness()


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


@dataclass(frozen=True)
class ProjectSummary:
    project_id: str
    title: str
    status: str
    created_at: str


def list_projects(config: PipelineConfig) -> list[ProjectSummary]:
    """Return all stored projects (newest first) for the resume picker.

    Read-only: opens the DB read-only and returns an empty list when no DB
    exists yet.
    """
    if not Path(config.db_path).exists():
        return []
    conn = connect_readonly_db(config.db_path)
    try:
        rows = conn.execute(
            "SELECT id, source_title, status, created_at FROM projects "
            "ORDER BY created_at DESC, id DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        ProjectSummary(
            project_id=row[0], title=row[1] or "", status=row[2], created_at=row[3]
        )
        for row in rows
    ]


def _load_artifact(config: PipelineConfig, project_id: str, filename: str, model):
    """Load and validate one stored JSON artifact, or return None if absent.

    Read-only. A missing file yields None; a present-but-invalid file raises so
    the corruption surfaces rather than being silently hidden.
    """
    path = config.projects_root / project_id / filename
    if not path.exists():
        return None
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def load_b_plan(config: PipelineConfig, project_id: str) -> BScenePlan | None:
    return _load_artifact(config, project_id, "b_scene_plan.json", BScenePlan)


def load_timeline(config: PipelineConfig, project_id: str) -> TimelineJson | None:
    return _load_artifact(config, project_id, "timeline.json", TimelineJson)


def load_e_script(config: PipelineConfig, project_id: str) -> EScript | None:
    return _load_artifact(config, project_id, "e_script.json", EScript)


def load_f_manifest(config: PipelineConfig, project_id: str) -> FKdenliveManifest | None:
    return _load_artifact(config, project_id, "f_kdenlive_manifest.json", FKdenliveManifest)


def load_candidate(config: PipelineConfig, project_id: str) -> dict[str, Any] | None:
    """Reconstruct an editable candidate dict from the stored source.json.

    Read-only. Returns None when the project's source artifact is absent. Used
    to re-edit or regenerate from the same source without re-typing.
    """
    source = _load_artifact(config, project_id, "source.json", SourceArtifact)
    if source is None:
        return None
    return {
        "candidate_id": f"regen-{project_id}",
        "title": source.source_title,
        "source_url": str(source.source_url),
        "community": source.source_community,
        "collected_at": source.created_at,
        "summary": source.user_or_llm_summary,
        "hook": source.hook,
        "why_shortable": source.why_shortable,
        "risk_flags_for_user": list(source.risk_flags_for_user),
        "status": "selected",
    }


def regenerate_draft(config: PipelineConfig, project_id: str, *, clock: Clock = None) -> str:
    """Create a NEW project from the same candidate and run A->F again.

    In-place stage re-runs are intentionally not offered (the phase services
    enforce forward-only preconditions). Regenerating as a fresh project is the
    safe, state-machine-respecting way to get a new draft (a real LLM yields a
    different take). Returns the new project id.
    """
    candidate = load_candidate(config, project_id)
    if candidate is None:
        raise ValueError(f"no stored candidate for project {project_id}")
    result = run_full_pipeline(config, candidate, clock=clock)
    return result["project_id"]


def store_user_image(
    config: PipelineConfig,
    project_id: str,
    relative_image_path: str,
    data: bytes,
    *,
    filename: str,
) -> str:
    """Validate an uploaded image and write it into the project's slot path.

    Local-only: rejects unsupported extensions, oversized files, empty data,
    and any path escaping the project directory. No external fetch occurs; the
    bytes come from the user's own upload. Returns the stored relative path.
    """
    if not data:
        raise UserImageError("uploaded file is empty")
    if len(data) > MAX_USER_IMAGE_BYTES:
        limit_mb = MAX_USER_IMAGE_BYTES // (1024 * 1024)
        raise UserImageError(f"image exceeds the {limit_mb} MB limit")
    try:
        validate_media_extension(filename)
        safe_relative = ensure_relative_project_path(relative_image_path)
        project_dir = Path(config.projects_root) / project_id
        target = ensure_path_under_root(project_dir, project_dir / safe_relative)
    except ValueError as exc:
        raise UserImageError(str(exc)) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return safe_relative.as_posix()


# --- Source discovery (opt-in, legal) ---------------------------------------

SOURCE_KINDS = ("rss", "link", "youtube", "naver")


def discover_candidates(kind: str, query: str = "") -> list[DiscoveredCandidate]:
    """Run one discovery provider by kind and return bounded candidates.

    Network egress happens only here, only when the user triggers it. Providers
    are opt-in (YouTube/Naver need keys) and never bypass blocks.
    """
    if kind == "rss":
        provider = RssSourceProvider()
    elif kind == "link":
        provider = SingleLinkFetchProvider()
    elif kind == "youtube":
        provider = YouTubeSourceProvider()
    elif kind == "naver":
        provider = NaverSearchSourceProvider()
    else:
        raise SourceError(f"알 수 없는 소스 종류: {kind}")
    return provider.discover(query)


def draft_candidate_from_discovered(discovered: Mapping[str, Any]) -> dict[str, Any]:
    """Turn a discovered item into an editable candidate dict for A->F.

    Only the bounded title/url/source/excerpt feed the draft - no full body.
    The summary/hook are auto-filled and meant to be edited by the user.
    """
    title = (str(discovered.get("title") or "")).strip() or "제목 없음"
    url = str(discovered.get("url") or "")
    source = (str(discovered.get("source") or "")).strip() or "discovery"
    excerpt = (str(discovered.get("excerpt") or "")).strip()
    slug = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return {
        "candidate_id": f"disc-{slug}",
        "title": title[:200],
        "source_url": url,
        "community": source[:60],
        "collected_at": "2026-01-01T00:00:00+09:00",
        "summary": (excerpt or title)[:500],
        "hook": title[:60],
        "why_shortable": "사용자가 고른 화제 후보입니다.",
        "risk_flags_for_user": [],
        "status": "selected",
    }


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
