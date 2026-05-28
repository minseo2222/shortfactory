from __future__ import annotations

import pytest

from shorts_pipeline.state_machine import (
    InvalidProjectStatusError,
    InvalidTransitionError,
    assert_transition_allowed,
    can_transition,
)


def test_valid_state_transition() -> None:
    assert can_transition("candidate_selected", "planned")
    assert_transition_allowed("candidate_selected", "planned")


def test_invalid_state_transition() -> None:
    assert not can_transition("candidate_selected", "completed")
    with pytest.raises(InvalidTransitionError):
        assert_transition_allowed("candidate_selected", "completed")


def test_unknown_state_rejected() -> None:
    with pytest.raises(InvalidProjectStatusError):
        assert_transition_allowed("unknown", "planned")
