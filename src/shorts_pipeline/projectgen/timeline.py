"""Timeline generation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from shorts_pipeline.models import BScenePlan, SourceArtifact, TimelineJson

TIMELINE_SOURCE_KEYS = (
    "source_url",
    "source_community",
    "source_title",
    "user_or_llm_summary",
    "hook",
    "why_shortable",
    "risk_flags_for_user",
)


def _scene_to_dict(scene: Any) -> dict[str, Any]:
    if hasattr(scene, "model_dump"):
        return scene.model_dump()
    if isinstance(scene, Mapping):
        return dict(scene)
    raise TypeError("scene must be a mapping or Pydantic model")


def assign_start_times(scenes: Sequence[Any]) -> list[dict[str, Any]]:
    """Return scene dictionaries with C-computed `start_sec` values."""
    current_start = 0.0
    output: list[dict[str, Any]] = []
    for scene in scenes:
        scene_data = _scene_to_dict(scene)
        scene_data["start_sec"] = round(current_start, 3)
        output.append(scene_data)
        current_start = round(current_start + float(scene_data["duration_sec"]), 3)
    return output


def source_metadata_for_timeline(source: SourceArtifact) -> dict[str, Any]:
    """Return the safe minimal source metadata allowed inside timeline.json."""
    source_data = source.model_dump(mode="json")
    return {key: source_data[key] for key in TIMELINE_SOURCE_KEYS}


def build_timeline_from_b_plan(
    plan: BScenePlan,
    *,
    source: SourceArtifact,
    project_id: str,
) -> TimelineJson:
    """Build a minimal validated timeline from a validated B scene plan."""
    timed_scenes = assign_start_times(plan.scene_plan)
    timeline_scenes: list[dict[str, Any]] = []
    for index, scene in enumerate(timed_scenes, start=1):
        scene_id = scene["scene_id"]
        slot_id = f"slot_{index:03d}"
        timeline_scenes.append(
            {
                "scene_id": scene_id,
                "start_sec": scene["start_sec"],
                "duration_sec": scene["duration_sec"],
                "screen_text": scene["screen_text"],
                "image_slot_id": slot_id,
                "image_slot_description": scene["image_slot_description"],
                "narration_intent": scene["narration_intent"],
                "bgm_instruction": None,
                "transition": "cut",
                "fact_basis": scene["source_basis"],
                "avoid_claims": scene["do_not_say"],
                "image_path": f"assets/user_images/{slot_id}.png",
                "text_overlay_path": f"assets/text_overlays/{scene_id}_text.png",
            }
        )
    total_duration = round(sum(scene.duration_sec for scene in plan.scene_plan), 3)
    return TimelineJson(
        project_id=project_id,
        canvas={"duration_target_sec": plan.target_duration_sec},
        source=source_metadata_for_timeline(source),
        style=plan.selected_style,
        total_duration_sec=total_duration,
        scenes=timeline_scenes,
    )
