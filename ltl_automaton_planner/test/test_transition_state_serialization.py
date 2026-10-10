"""Tests for planner-local transition-state serialization."""

from functools import partial
from types import SimpleNamespace

import pytest

from ltl_automaton_msgs.msg import LTLPlan
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


def _counted_message_node(planner):
    records = {"dimension_calls": 0, "published": [], "logs": []}

    def dimension_names(target):
        records["dimension_calls"] += 1
        return PlannerNode._planner_dimension_names(target)

    logger = SimpleNamespace(
        info=lambda text: records["logs"].append(("info", text)),
        warning=lambda text: records["logs"].append(("warning", text)),
    )
    node = SimpleNamespace(
        ltl_planner=planner,
        _planner_dimension_names=dimension_names,
        get_logger=lambda: logger,
        possible_states_publisher=SimpleNamespace(
            publish=records["published"].append,
        ),
    )
    node._state_to_message = partial(PlannerNode._state_to_message, node)
    return node, records


def _assert_independent_state_lists(messages):
    assert len({id(message.states) for message in messages}) == len(messages)
    assert len({id(message.state_dimension_names) for message in messages}) == len(messages)


@pytest.mark.parametrize("empty_prefix", [False, True])
@pytest.mark.parametrize("state_format", [[["pose"], ["gripper"]], []])
def test_plan_batch_preserves_payload_and_refreshes_independent_lists(empty_prefix, state_format):
    """Reuse dimensions within a plan while keeping each message and call independent."""
    planner = _planner_with_state_format(state_format)
    line = [] if empty_prefix else [("k0", "empty"), ("k1", "holding")]
    loop = [("k1", "holding"), ("k0", "empty"), ("k1", "holding")]
    planner.run = SimpleNamespace(
        line=line,
        loop=loop,
        pre_plan=[] if empty_prefix else ["move"],
        suf_plan=["release", "grasp", "wait"],
    )
    original_run = tuple(
        tuple(getattr(planner.run, name))
        for name in ("line", "loop", "pre_plan", "suf_plan")
    )
    node, records = _counted_message_node(planner)
    stamp = LTLPlan().header.stamp
    stamp.sec = 12
    stamp.nanosec = 345

    prefix, suffix = PlannerNode._plan_messages(node, planner, stamp)

    assert prefix.header.stamp == suffix.header.stamp == stamp
    assert prefix.action_sequence == planner.run.pre_plan
    assert suffix.action_sequence == planner.run.suf_plan
    assert [message.states for message in prefix.ts_state_sequence] == [list(s) for s in line]
    assert [message.states for message in suffix.ts_state_sequence] == [list(s) for s in loop]
    messages = list(prefix.ts_state_sequence) + list(suffix.ts_state_sequence)
    expected_names = flatten_state_dimension_names(state_format)
    assert all(message.state_dimension_names == expected_names for message in messages)
    assert records["dimension_calls"] == 1
    _assert_independent_state_lists(messages)

    messages[0].states[0] = "changed"
    messages[0].state_dimension_names.append("changed")
    assert [message.states for message in messages[1:]] == [list(s) for s in (line + loop)[1:]]
    assert all(message.state_dimension_names == expected_names for message in messages[1:])
    planner.product.graph["ts"].graph["ts_state_format"] = [["location"], ["tool"]]

    next_prefix, next_suffix = PlannerNode._plan_messages(node, planner, stamp)

    next_messages = list(next_prefix.ts_state_sequence) + list(next_suffix.ts_state_sequence)
    assert records["dimension_calls"] == 2
    assert all(message.state_dimension_names == ["location", "tool"] for message in next_messages)
    assert [message.states for message in next_messages] == [list(s) for s in line + loop]
    assert all(message.state_dimension_names == expected_names for message in messages[1:])
    assert tuple(
        tuple(getattr(planner.run, name))
        for name in ("line", "loop", "pre_plan", "suf_plan")
    ) == original_run


@pytest.mark.parametrize("graph", [{}, {"ts": SimpleNamespace(graph={"ts_state_format": None})}])
def test_empty_plan_does_not_read_dimension_metadata(graph):
    """Preserve empty plans even when unused TS metadata is unavailable."""
    planner = SimpleNamespace(
        product=SimpleNamespace(graph=graph),
        run=SimpleNamespace(line=[], loop=[], pre_plan=[], suf_plan=[]),
    )
    node, records = _counted_message_node(planner)
    stamp = LTLPlan().header.stamp

    prefix, suffix = PlannerNode._plan_messages(node, planner, stamp)

    assert prefix == suffix == LTLPlan()
    assert records["dimension_calls"] == 0


def test_possible_state_batch_preserves_order_logs_and_independent_lists():
    """Publish every ordered Product state with independent fields and refreshed dimensions."""
    planner = _planner_with_state_format([["pose"], ["gripper"]])
    states = {(("k1", "holding"), "q2"), (("k0", "empty"), "q1"), (("k0", "empty"), "q0")}
    planner.product.possible_states = states
    original_states = frozenset(states)
    node, records = _counted_message_node(planner)
    expected = [(list(ts), str(buchi)) for ts, buchi in sorted(states, key=str)]

    PlannerNode._publish_possible_states(node)

    messages = records["published"][0].ltl_states
    assert [(message.ts_state.states, message.buchi_state) for message in messages] == expected
    assert records["logs"] == [
        ("info", f"Publishing possible LTL states: {expected}"),
        ("info", "Published 3 possible LTL states."),
    ]
    assert records["dimension_calls"] == 1
    ts_messages = [message.ts_state for message in messages]
    _assert_independent_state_lists(ts_messages)
    ts_messages[0].states[0] = "changed"
    ts_messages[0].state_dimension_names.append("changed")
    assert [message.states for message in ts_messages[1:]] == [ts for ts, _ in expected[1:]]
    assert all(message.state_dimension_names == ["pose", "gripper"] for message in ts_messages[1:])
    planner.product.graph["ts"].graph["ts_state_format"] = [["location"], ["tool"]]

    PlannerNode._publish_possible_states(node)

    refreshed = records["published"][1].ltl_states
    assert [(message.ts_state.states, message.buchi_state) for message in refreshed] == expected
    assert all(
        message.ts_state.state_dimension_names == ["location", "tool"]
        for message in refreshed
    )
    assert all(message.state_dimension_names == ["pose", "gripper"] for message in ts_messages[1:])
    assert records["dimension_calls"] == 2
    assert planner.product.possible_states == original_states


def test_empty_possible_state_batch_publishes_without_dimension_metadata():
    """Keep empty publication and its logs without accessing an absent TS graph."""
    planner = SimpleNamespace(product=SimpleNamespace(graph={}, possible_states=set()))
    node, records = _counted_message_node(planner)

    PlannerNode._publish_possible_states(node)

    assert records["dimension_calls"] == 0
    assert records["published"][0].ltl_states == []
    assert records["logs"] == [
        ("info", "Publishing possible LTL states: []"),
        ("info", "Published 0 possible LTL states."),
    ]


@pytest.mark.parametrize("publication", [False, True])
def test_bad_state_keeps_priority_over_bad_dimension_metadata(publication):
    """Report the first state conversion error before reading malformed dimensions."""
    class BadState:
        def __str__(self):
            raise ValueError("state conversion failed")

    planner = _planner_with_state_format(None)
    state = (BadState(), "holding")
    planner.run = SimpleNamespace(line=[state], loop=[], pre_plan=[], suf_plan=[])
    planner.product.possible_states = {(state, "q0")}
    node, records = _counted_message_node(planner)

    with pytest.raises(ValueError, match="^state conversion failed$"):
        if publication:
            PlannerNode._publish_possible_states(node)
        else:
            PlannerNode._plan_messages(node, planner, LTLPlan().header.stamp)

    assert records["dimension_calls"] == 0
    assert records["published"] == []
