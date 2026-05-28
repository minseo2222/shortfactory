"""Validation helpers for LLM-shaped artifacts.

This module intentionally contains no external provider API calls.
"""

from __future__ import annotations

from typing import Any

from shorts_pipeline.models import BScenePlan, DImageManifest, EScript


class ArtifactNotReadyError(ValueError):
    """Raised when a downstream artifact is not safe to generate."""


def validate_b_scene_plan(data: dict[str, Any]) -> BScenePlan:
    """Validate B output before artifact storage."""
    return BScenePlan.model_validate(data)


def validate_e_script(data: dict[str, Any]) -> EScript:
    """Validate E output before artifact storage."""
    return EScript.model_validate(data)


def assert_manifest_ready_for_e(manifest: DImageManifest) -> None:
    """Block E generation until user image insertion and rights checks are complete."""
    if (
        not manifest.image_insert_completed
        or not manifest.user_confirmed
        or manifest.completed_at is None
    ):
        raise ArtifactNotReadyError("D image manifest is not user-confirmed")

    unconfirmed_slots = [
        slot.slot_id for slot in manifest.slots if not slot.rights_confirmed_by_user
    ]
    if unconfirmed_slots:
        joined = ", ".join(unconfirmed_slots)
        raise ArtifactNotReadyError(f"rights not confirmed for slots: {joined}")

    unsafe_slots = [
        slot.slot_id
        for slot in manifest.slots
        if slot.contains_personal_info
        or slot.contains_original_capture
        or slot.contains_community_logo
        or (slot.contains_face and slot.face_rights_confirmed is not True)
    ]
    if unsafe_slots:
        joined = ", ".join(unsafe_slots)
        raise ArtifactNotReadyError(f"unsafe image metadata for slots: {joined}")


def can_generate_e_script(manifest: DImageManifest) -> bool:
    try:
        assert_manifest_ready_for_e(manifest)
    except ArtifactNotReadyError:
        return False
    return True
