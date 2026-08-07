"""Tests for deterministic KTH demo state transitions."""

import pytest

from ltl_automaton_planner.kth_demo_driver import next_state_for_action


@pytest.mark.parametrize(
    "state, action, expected",
    [
        (("r1", "unloaded"), "goto_r2", ("r2", "unloaded")),
        (("r1", "loaded"), "goto_r3", ("r3", "loaded")),
        (("r3", "loaded"), "goto_r1", ("r1", "loaded")),
        (("r2", "unloaded"), "pick", ("r2", "loaded")),
        (("r2", "loaded"), "drop", ("r2", "unloaded")),
    ],
)
def test_next_state_for_action(state, action, expected):
    """Apply each supported action without changing unrelated dimensions."""
    assert next_state_for_action(state, action) == expected


@pytest.mark.parametrize(
    "state, action",
    [
        (("r1", "unloaded"), "pick"),
        (("r2", "loaded"), "pick"),
        (("r2", "unloaded"), "drop"),
        (("r1", "unloaded"), "unknown"),
    ],
)
def test_next_state_for_action_rejects_invalid_transition(state, action):
    """Reject actions that violate the KTH example transition guards."""
    with pytest.raises(ValueError):
        next_state_for_action(state, action)
