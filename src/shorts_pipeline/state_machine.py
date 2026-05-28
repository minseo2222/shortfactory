"""Project status transition rules."""

from __future__ import annotations

PROJECT_STATUSES: tuple[str, ...] = (
    "candidate_selected",
    "planned",
    "project_generated",
    "waiting_for_user_images",
    "images_inserted",
    "script_generated",
    "recording_done",
    "final_editing",
    "completed",
    "archived",
    "failed",
)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "candidate_selected": {"planned", "failed"},
    "planned": {"project_generated", "failed"},
    "project_generated": {"waiting_for_user_images", "images_inserted", "failed"},
    "waiting_for_user_images": {"images_inserted", "failed"},
    "images_inserted": {"script_generated", "failed"},
    "script_generated": {"recording_done", "failed"},
    "recording_done": {"final_editing", "failed"},
    "final_editing": {"completed", "failed"},
    "completed": {"archived"},
    "archived": set(),
    "failed": set(),
}


class InvalidProjectStatusError(ValueError):
    """Raised when a status is not part of the v2.1 project state set."""


class InvalidTransitionError(ValueError):
    """Raised when a project status transition is not allowed."""


def is_valid_status(status: str) -> bool:
    return status in PROJECT_STATUSES


def can_transition(current: str, target: str) -> bool:
    if not is_valid_status(current) or not is_valid_status(target):
        return False
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition_allowed(current: str, target: str) -> None:
    if not is_valid_status(current):
        raise InvalidProjectStatusError(f"unknown current status: {current}")
    if not is_valid_status(target):
        raise InvalidProjectStatusError(f"unknown target status: {target}")
    if not can_transition(current, target):
        raise InvalidTransitionError(f"cannot transition from {current} to {target}")
