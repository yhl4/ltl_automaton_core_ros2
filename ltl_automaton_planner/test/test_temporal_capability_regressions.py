"""E2E-1 formal temporal capability regressions for frozen Demo-D1."""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from action_msgs.msg import GoalStatus
import pytest
import rclpy
from rclpy.action import ActionClient
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
import yaml

from ltl_automaton_msgs.action import PlanLTL
from ltl_automaton_planner_core.configuration.transition_system import (
    state_models_from_ts,
)
from ltl_automaton_planner_core.ltl_tools.ltl_planner import LTLPlanner
from ltl_automaton_planner_core.ltl_tools.ts import TSModel
from ltl_automaton_planner.planner_node import PlannerNode

from test_plan_ltl_action import action_result
from test_plan_ltl_action import get_planning_graph_snapshot
from test_plan_ltl_action import load_transition_system
from test_plan_ltl_action import send_goal


FIXTURE = (
    Path(__file__).parents[1]
    / "config"
    / "demo_d1_household_ts.yaml"
)
DIMENSIONS = ["2d_pose_region", "gripper_state"]
INITIAL = ["l0", "empty"]
NEUTRAL = "(b0 || ! b0)"


@dataclass(frozen=True)
class TemporalCase:
    """One direct-formula capability owned by the formal planner."""

    case_id: str
    hard_task: str


CASES = (
    TemporalCase("B2", "<>(holding) && []!(b0 && holding)"),
    TemporalCase("C1", "<>(k0 && <>(b0))"),
    TemporalCase("C2", "<>(b0 && <>(s0))"),
    TemporalCase("C3", "<>(holding && <>(k0))"),
    TemporalCase("D1", "(!b0) U k0"),
    TemporalCase("D2", "(!b0) U (k0 && <>(b0))"),
    TemporalCase("D3", "(!s0) U b0"),
    TemporalCase("E4", "[]<>(k0) && []!d0"),
    TemporalCase("F1", "<>[](k0)"),
    TemporalCase("F2", "<>[](b0)"),
    TemporalCase(
        "H3",
        "<>(holding && ((!empty) U (s0 && holding && <>(empty))))",
    ),
    TemporalCase("Q1", "<>(k0) && <>(b0)"),
)


@pytest.fixture
def temporal_action_runtime():
    """Run an isolated public PlanLTL client and real planner node."""
    context = Context()
    rclpy.init(context=context)
    planner = PlannerNode(context=context)
    client_node = rclpy.create_node(
        "temporal_capability_action_test",
        context=context,
    )
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(planner)
    executor.add_node(client_node)
    action_client = ActionClient(client_node, PlanLTL, "plan_ltl")
    runtime = SimpleNamespace(
        context=context,
        planner=planner,
        client_node=client_node,
        executor=executor,
        action_client=action_client,
    )
    assert action_client.wait_for_server(timeout_sec=2.0)

    try:
        yield runtime
    finally:
        executor.remove_node(client_node)
        executor.remove_node(planner)
        action_client.destroy()
        client_node.destroy_node()
        planner.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)


def _transition_system():
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    model = TSModel(state_models_from_ts(data))
    model.build_full()
    return model


def _plan(hard_task):
    planner = LTLPlanner(
        _transition_system(),
        hard_spec=hard_task,
        soft_spec=NEUTRAL,
        beta=1000,
        gamma=10,
    )
    assert planner.optimal(style="static") is True
    return planner


def _first_region(states, region):
    return next(
        index for index, state in enumerate(states) if state[0] == region
    )


def _first_gripper(states, gripper):
    return next(
        index for index, state in enumerate(states) if state[1] == gripper
    )


def _assert_temporal_semantics(case_id, planner):
    prefix = list(planner.run.line)
    suffix = list(planner.run.loop)
    all_states = prefix + suffix

    if case_id == "B2":
        assert "pick" in planner.run.pre_plan
        assert any(state[1] == "holding" for state in prefix)
        assert all(state != ("b0", "holding") for state in all_states)
    elif case_id == "C1":
        assert _first_region(prefix, "k0") < _first_region(prefix, "b0")
    elif case_id == "C2":
        assert _first_region(prefix, "b0") < _first_region(prefix, "s0")
    elif case_id == "C3":
        assert _first_gripper(prefix, "holding") < _first_region(prefix, "k0")
    elif case_id == "D1":
        kitchen = _first_region(prefix, "k0")
        assert all(state[0] != "b0" for state in prefix[:kitchen])
    elif case_id == "D2":
        kitchen = _first_region(prefix, "k0")
        bedroom = _first_region(prefix, "b0")
        assert all(state[0] != "b0" for state in prefix[:kitchen])
        assert kitchen < bedroom
    elif case_id == "D3":
        bedroom = _first_region(prefix, "b0")
        assert all(state[0] != "s0" for state in prefix[:bedroom])
    elif case_id == "E4":
        assert all(state[0] != "d0" for state in all_states)
        assert any(state[0] == "k0" for state in suffix)
    elif case_id == "F1":
        assert suffix and all(state[0] == "k0" for state in suffix)
    elif case_id == "F2":
        assert suffix and all(state[0] == "b0" for state in suffix)
    elif case_id == "H3":
        pick = planner.run.pre_plan.index("pick")
        place = planner.run.pre_plan.index("place")
        study = next(
            index
            for index, state in enumerate(prefix)
            if state == ("s0", "holding")
        )
        assert pick < study <= place
        assert prefix[pick + 1][1] == "holding"
        assert prefix[place + 1][1] == "empty"
    elif case_id == "Q1":
        assert _first_region(prefix, "b0") < _first_region(prefix, "k0")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_temporal_capability(case):
    """Freeze semantic run properties without graph-node identifiers."""
    planner = _plan(case.hard_task)

    assert planner.run.line
    assert planner.run.loop
    _assert_temporal_semantics(case.case_id, planner)


def test_temporal_contrast_unordered_ordered_and_until():
    """Keep one-time, ordered, and Until specifications distinct."""
    unordered = _plan("<>(k0) && <>(b0)").run.line
    ordered = _plan("<>(k0 && <>(b0))").run.line
    until = _plan("(!b0) U k0").run.line
    until_then = _plan("(!b0) U (k0 && <>(b0))").run.line

    assert _first_region(unordered, "b0") < _first_region(unordered, "k0")
    assert _first_region(ordered, "k0") < _first_region(ordered, "b0")
    until_kitchen = _first_region(until, "k0")
    assert all(state[0] != "b0" for state in until[:until_kitchen])
    until_then_kitchen = _first_region(until_then, "k0")
    assert all(
        state[0] != "b0"
        for state in until_then[:until_then_kitchen]
    )
    assert until_then_kitchen < _first_region(until_then, "b0")


def test_temporal_contrast_eventuality_recurrence_and_persistence():
    """Document distinct formulas even when wait loops yield the same route."""
    eventual = _plan("<>(k0)")
    recurrent = _plan("[]<>(k0)")
    persistent = _plan("<>[](k0)")

    assert all(
        planner.run.line for planner in (eventual, recurrent, persistent)
    )
    assert any(state[0] == "k0" for state in recurrent.run.loop)
    assert all(state[0] == "k0" for state in persistent.run.loop)


def test_temporal_capability_n3b_no_accepting_plan_keeps_generation(
    temporal_action_runtime,
):
    """Freeze the clean known-but-unrealizable public action result."""
    action_runtime = temporal_action_runtime
    yaml_text = FIXTURE.read_text(encoding="utf-8")
    assert load_transition_system(action_runtime, yaml_text).success
    before = get_planning_graph_snapshot(action_runtime)

    goal = PlanLTL.Goal()
    goal.hard_task = "[](!empty)"
    goal.soft_task = NEUTRAL
    goal.initial_state.state_dimension_names = DIMENSIONS
    goal.initial_state.states = INITIAL
    goal.beta = 1000.0
    goal.gamma = 10.0
    goal_handle = send_goal(action_runtime, goal)
    assert goal_handle.accepted
    response = action_result(action_runtime, goal_handle)
    after = get_planning_graph_snapshot(action_runtime)

    assert response.status == GoalStatus.STATUS_ABORTED
    assert not response.result.success
    assert response.result.error_code == PlanLTL.Result.ERROR_NO_ACCEPTING_PLAN
    assert response.result.message == "No accepting LTL plan was found."
    assert after.snapshot.metadata.planning_generation == (
        before.snapshot.metadata.planning_generation
    )
