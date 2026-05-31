"""Pydantic data contracts for Shorts Pipeline v2.1."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

CandidateStatus = Literal["new", "selected", "rejected_in_session"]
SceneId = str
SlotId = str
ShortsStyle = Literal[
    "뉴스/이슈 요약형",
    "썰형",
    "댓글 반응 중계형",
    "논쟁 유도형",
    "밈/반응형",
]
ScenePurpose = Literal[
    "hook",
    "context",
    "turn",
    "reaction",
    "contrast",
    "payoff",
    "cta",
]


def _expected_scene_ids(count: int) -> list[str]:
    return [f"s{index:02d}" for index in range(1, count + 1)]


def _looks_like_direct_quote(text: str) -> bool:
    stripped = text.strip()
    quote_pairs = [('"', '"'), ("'", "'"), ("`", "`"), ("\u201c", "\u201d")]
    return any(
        len(stripped) > 8 and stripped.startswith(start) and stripped.endswith(end)
        for start, end in quote_pairs
    )


def _reject_external_or_traversal(path: str) -> None:
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc:
        raise ValueError("external resources are not allowed")
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        raise ValueError("path must stay relative to the project")


class StrictModel(BaseModel):
    """Base model that rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid")


class CandidateCard(StrictModel):
    candidate_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: AnyUrl
    community: str = Field(min_length=1)
    collected_at: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    why_shortable: str = Field(min_length=1)
    risk_flags_for_user: list[str] = Field(default_factory=list)
    status: CandidateStatus = "new"


class SourceStoragePolicy(StrictModel):
    full_source_post_stored: Literal[False] = False
    full_comments_stored: Literal[False] = False
    original_screenshot_stored: Literal[False] = False


class SourceArtifact(StrictModel):
    schema_version: Literal["source.v2.1"] = "source.v2.1"
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    source_url: AnyUrl
    source_community: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    user_or_llm_summary: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    why_shortable: str = Field(min_length=1)
    risk_flags_for_user: list[str] = Field(default_factory=list)
    created_at: str = Field(min_length=1)
    storage_policy: SourceStoragePolicy = Field(default_factory=SourceStoragePolicy)


class Project(StrictModel):
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    status: Literal["candidate_selected"]
    project_dir: str = Field(min_length=1)
    source_json_path: str = Field(min_length=1)
    created_at: str = Field(min_length=1)


class ScenePlanItem(StrictModel):
    scene_id: SceneId = Field(pattern=r"^s\d{2}$")
    duration_sec: float = Field(gt=1.0, le=12.0)
    purpose: ScenePurpose
    screen_text: str = Field(min_length=1, max_length=40)
    visual_direction: str = Field(min_length=1, max_length=300)
    image_slot_description: str = Field(min_length=1, max_length=300)
    narration_intent: str = Field(min_length=1, max_length=300)
    source_basis: list[str] = Field(min_length=1, max_length=5)
    do_not_say: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("screen_text")
    @classmethod
    def screen_text_must_not_look_quoted(cls, value: str) -> str:
        if _looks_like_direct_quote(value):
            raise ValueError("screen_text must not look like a direct quote")
        return value


class BScenePlan(StrictModel):
    schema_version: Literal["b_scene_plan.v2.1"] = "b_scene_plan.v2.1"
    selected_style: ShortsStyle
    style_reason: str = Field(min_length=1, max_length=500)
    target_duration_sec: int = Field(ge=30, le=60)
    scene_plan: list[ScenePlanItem] = Field(min_length=4, max_length=12)
    risk_flags: list[str] = Field(default_factory=list, max_length=12)


class CanvasSpec(StrictModel):
    width: int = Field(default=1080, gt=0)
    height: int = Field(default=1920, gt=0)
    fps: int = Field(default=30, gt=0)
    duration_target_sec: int = Field(default=30, ge=30, le=60)


TimelineTransition = Literal["cut", "quick_zoom", "fade", "none"]


class TimelineScene(StrictModel):
    scene_id: SceneId = Field(pattern=r"^s\d{2}$")
    start_sec: float = Field(ge=0.0)
    duration_sec: float = Field(gt=1.0, le=12.0)
    screen_text: str = Field(min_length=1, max_length=40)
    image_slot_id: SlotId = Field(pattern=r"^slot_\d{3}$")
    image_slot_description: str = Field(min_length=1, max_length=300)
    narration_intent: str = Field(min_length=1, max_length=300)
    bgm_instruction: str | None = None
    transition: TimelineTransition = "cut"
    fact_basis: list[str] = Field(min_length=1, max_length=5)
    avoid_claims: list[str] = Field(default_factory=list, max_length=10)
    image_path: str = Field(min_length=1)
    text_overlay_path: str = Field(min_length=1)

    @field_validator("image_path", "text_overlay_path")
    @classmethod
    def paths_must_be_project_relative(cls, value: str) -> str:
        _reject_external_or_traversal(value)
        return value


class TimelineJson(StrictModel):
    schema_version: Literal["timeline.v2.1"] = "timeline.v2.1"
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    canvas: CanvasSpec
    source: dict[str, Any]
    style: ShortsStyle
    total_duration_sec: float = Field(ge=30.0, le=60.0)
    scenes: list[TimelineScene] = Field(min_length=4, max_length=12)

    @model_validator(mode="after")
    def validate_scene_timing(self) -> "TimelineJson":
        actual_ids = [scene.scene_id for scene in self.scenes]
        if actual_ids != _expected_scene_ids(len(self.scenes)):
            raise ValueError("timeline scene_id values must be consecutive starting at s01")

        expected_start = 0.0
        for scene in self.scenes:
            rounded_start = round(expected_start, 3)
            if abs(scene.start_sec - rounded_start) > 0.001:
                raise ValueError("timeline start_sec values must be duration accumulation")
            expected_start += scene.duration_sec

        if abs(self.total_duration_sec - round(expected_start, 3)) > 0.001:
            raise ValueError("total_duration_sec must equal scene duration sum")
        return self


ImageSlotStatus = Literal["placeholder", "replaced"]
ImageSourceType = Literal[
    "app_generated_placeholder",
    "user_owned",
    "licensed_stock",
    "creative_commons",
    "public_domain",
    "permission_obtained",
    "ai_generated_by_user",
    "fair_use_reviewed",
]


class DImageSlotManifest(StrictModel):
    slot_id: SlotId = Field(pattern=r"^slot_\d{3}$")
    scene_id: SceneId = Field(pattern=r"^s\d{2}$")
    status: ImageSlotStatus
    planned_image_path: str
    actual_image_path: str
    actual_image_note: str | None = Field(default=None, max_length=300)
    source_type: ImageSourceType
    rights_confirmed_by_user: bool
    contains_face: bool = False
    face_rights_confirmed: bool | None = None
    contains_personal_info: bool = False
    contains_original_capture: bool = False
    contains_community_logo: bool = False
    image_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("planned_image_path", "actual_image_path")
    @classmethod
    def image_paths_must_be_project_relative(cls, value: str) -> str:
        _reject_external_or_traversal(value)
        return value

    @model_validator(mode="after")
    def replaced_slots_need_notes(self) -> "DImageSlotManifest":
        if self.status == "replaced" and not (self.actual_image_note or "").strip():
            raise ValueError("replaced slots require actual_image_note")
        return self


DImageSlotManifestItem = DImageSlotManifest


class DImageManifest(StrictModel):
    schema_version: Literal["d_image_manifest.v2.1"] = "d_image_manifest.v2.1"
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    image_insert_completed: bool = False
    user_confirmed: bool = False
    completed_at: datetime | None = None
    slots: list[DImageSlotManifest] = Field(min_length=4, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_manifest_consistency(self) -> "DImageManifest":
        if self.image_insert_completed and not self.user_confirmed:
            raise ValueError("image_insert_completed requires user_confirmed")

        slot_ids = [slot.slot_id for slot in self.slots]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("slot_id values must be unique")
        return self


NarrationPace = Literal[
    "빠르게",
    "보통",
    "느리게",
]

TitleAngle = Literal[
    "분노/논쟁",
    "궁금증",
    "반전",
    "공감/혼란",
    "밈/반응",
]


class NarrationLine(StrictModel):
    scene_id: SceneId = Field(pattern=r"^s\d{2}$")
    pace: NarrationPace
    script: str = Field(min_length=1, max_length=280)
    optional_cut: str | None = Field(default=None, max_length=160)
    recording_note: str = Field(default="", max_length=180)
    fact_basis: list[str] = Field(default_factory=list, min_length=1, max_length=5)

    @field_validator("script")
    @classmethod
    def script_must_not_look_quoted(cls, value: str) -> str:
        if _looks_like_direct_quote(value):
            raise ValueError("script must not look like a direct quote")
        return value


class TitleCandidate(StrictModel):
    title: str = Field(min_length=1, max_length=60)
    angle: TitleAngle
    fact_safety_note: str = Field(min_length=1, max_length=240)


class EScript(StrictModel):
    schema_version: Literal["e_script.v2.1"] = "e_script.v2.1"
    narration_script: list[NarrationLine] = Field(min_length=4, max_length=12)
    title_candidates: list[TitleCandidate] = Field(min_length=5, max_length=12)
    recommended_title: str = Field(min_length=1, max_length=60)
    forbidden_claims: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_script_consistency(self) -> "EScript":
        candidate_titles = [candidate.title for candidate in self.title_candidates]
        if self.recommended_title not in candidate_titles:
            raise ValueError("recommended_title must be one of title_candidates")
        if len(candidate_titles) != len(set(candidate_titles)):
            raise ValueError("title_candidates must be unique")

        scene_ids = [line.scene_id for line in self.narration_script]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("narration_script scene_id values must be unique")
        return self


class FKdenliveSceneRef(StrictModel):
    scene_id: SceneId = Field(pattern=r"^s\d{2}$")
    image_slot_id: SlotId = Field(pattern=r"^slot_\d{3}$")
    start_sec: float = Field(ge=0.0)
    duration_sec: float = Field(gt=1.0, le=12.0)
    start_frame: int = Field(ge=0)
    duration_frames: int = Field(gt=0)
    image_path: str
    text_overlay_path: str
    narration_script_present: bool = True

    @field_validator("image_path", "text_overlay_path")
    @classmethod
    def paths_must_be_project_relative(cls, value: str) -> str:
        _reject_external_or_traversal(value)
        return value


class FKdenliveManifest(StrictModel):
    schema_version: Literal["f_kdenlive_project.v2.1"] = "f_kdenlive_project.v2.1"
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    kdenlive_project_path: str = "project.kdenlive"
    canvas_width: int = 1080
    canvas_height: int = 1920
    fps: int = 30
    total_duration_sec: float = Field(ge=30.0, le=60.0)
    total_frames: int = Field(gt=0)
    scenes: list[FKdenliveSceneRef] = Field(min_length=4, max_length=12)
    source_artifacts: dict[str, str]
    generated_at: datetime
    generated_by: str = "shortfactory"
    external_template_used: bool = False
    rendering_performed: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("kdenlive_project_path")
    @classmethod
    def kdenlive_path_must_be_project_relative(cls, value: str) -> str:
        _reject_external_or_traversal(value)
        return value

    @field_validator("source_artifacts")
    @classmethod
    def source_artifact_paths_must_be_project_relative(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        for path in value.values():
            _reject_external_or_traversal(path)
        return value

    @model_validator(mode="after")
    def validate_manifest_consistency(self) -> "FKdenliveManifest":
        if self.canvas_width != 1080 or self.canvas_height != 1920 or self.fps != 30:
            raise ValueError("F Kdenlive manifest must be 1080x1920 at 30fps")
        if self.total_frames != round(self.total_duration_sec * self.fps):
            raise ValueError("total_frames must equal rounded total duration frames")
        if self.external_template_used:
            raise ValueError("external_template_used must be false")
        if self.rendering_performed:
            raise ValueError("rendering_performed must be false")
        return self


class ProjectStatusEvent(StrictModel):
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    from_status: str | None = None
    to_status: str = Field(min_length=1)
    stage: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=100)
    created_at: datetime


class SmokeArtifactCheck(StrictModel):
    name: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    exists: bool
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SmokeRunResult(StrictModel):
    schema_version: Literal["smoke_run.v2.1"] = "smoke_run.v2.1"
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    final_status: str = Field(min_length=1)
    status_sequence: list[str] = Field(min_length=1)
    artifact_checks: list[SmokeArtifactCheck] = Field(default_factory=list)
    db_table_counts: dict[str, int] = Field(default_factory=dict)


class ArtifactInspectionRow(StrictModel):
    artifact_id: int | None = None
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    artifact_type: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    created_at: datetime | None = None
    exists: bool | None = None
    path_is_safe: bool
    sha256_matches: bool | None = None
    verification_error: str | None = None


class ProjectInspectionSummary(StrictModel):
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    status: str = Field(min_length=1)
    project_dir: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectInspectionResult(StrictModel):
    schema_version: Literal["project_inspection.v2.1"] = "project_inspection.v2.1"
    project: ProjectInspectionSummary
    status_sequence: list[str]
    status_events: list[ProjectStatusEvent]
    artifacts: list[ArtifactInspectionRow]
    artifact_problem_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class ProjectVerificationItem(StrictModel):
    name: str = Field(min_length=1)
    relative_path: str | None = None
    kind: str = Field(min_length=1)
    exists: bool | None = None
    valid: bool
    required: bool
    sha256_matches: bool | None = None
    problem: str | None = None


class ProjectFolderVerificationResult(StrictModel):
    schema_version: Literal["project_folder_verification.v2.1"] = (
        "project_folder_verification.v2.1"
    )
    project_id: str = Field(pattern=r"^PRJ_\d{8}_\d{4}$")
    project_status: str = Field(min_length=1)
    require_f: bool
    verified_a_to_e: bool
    verified_f: bool
    problem_count: int = Field(ge=0)
    items: list[ProjectVerificationItem]
    warnings: list[str] = Field(default_factory=list, max_length=50)


def model_validate_json_dict(model: type[StrictModel], data: dict[str, Any]) -> StrictModel:
    """Validate a JSON-like dictionary against one of the strict contracts."""
    return model.model_validate(data)
