"""Tests for planner-local transition-state serialization."""

from types import SimpleNamespace

import pytest

from ltl_automaton_planner.planner_node import PlannerNode
from ltl_automaton_planner.transition_state_serialization import (
    flatten_state_dimension_names,
    serialize_transition_state_values,
)


def _planner_with_state_format(state_format):
    transition_system = SimpleNamespace(
        graph={"ts_state_format": state_format},
    )
    product = SimpleNamespace(graph={"ts": transition_system})
    return SimpleNamespace(product=product)


def test_single_dimension_serialization_preserves_order_and_value():
    """Serialize one-dimensional metadata and state without reshaping."""
    assert flatten_state_dimension_names(["region"]) == ["region"]
    assert serialize_transition_state_values("r1") == ["r1"]


def test_demo_d1_style_serialization_preserves_compound_order():
    """Keep Demo-D1 dimensions and compound values in active TS order."""
    assert flatten_state_dimension_names(
        [["2d_pose_region"], ["gripper_state"]]
    ) == ["2d_pose_region", "gripper_state"]
    assert serialize_transition_state_values(("k0", "holding")) == [
        "k0",
        "holding",
    ]


def test_planner_ros_message_payload_remains_exact():
    """Keep PlannerNode ROS composition identical for compound state."""
    planner = _planner_with_state_format(
        [["2d_pose_region"], ["gripper_state"]]
    )
    node = SimpleNamespace(
        ltl_planner=planner,
        _planner_dimension_names=PlannerNode._planner_dimension_names,
    )

    message = PlannerNode._state_to_message(
        node,
        ("k0", "holding"),
    )

    assert list(message.state_dimension_names) == [
        "2d_pose_region",
        "gripper_state",
    ]
    assert list(message.states) == ["k0", "holding"]


def test_malformed_dimension_metadata_keeps_existing_failure():
    """Do not silently coerce non-iterable TS dimension metadata."""
    with pytest.raises(TypeError):
        flatten_state_dimension_names(None)
