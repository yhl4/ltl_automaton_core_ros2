"""Integration tests for the ROS-independent LTL planner."""

import shutil
from io import StringIO

import pytest

from ltl_automaton_planner_core.configuration.transition_system import (
    import_ts_from_file,
    state_models_from_ts,
)
from ltl_automaton_planner_core.ltl_tools.ltl_planner import (
    LTLPlanner,
)
from ltl_automaton_planner_core.ltl_tools.ts import TSModel


TS_YAML = """
state_dim:
  - region

state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to:
          r2: goto_r2
      r2:
        connected_to:
          r2: stay_r2

actions:
  goto_r2:
    guard: "1"
    weight: 2.0

  stay_r2:
    guard: "1"
    weight: 1.0
"""


BRANCHING_TS_YAML = """
state_dim:
  - region

state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to:
          r2: goto_r2
          r3: goto_r3
      r2:
        connected_to:
          r1: goto_r1
      r3:
        connected_to:
          r1: goto_r1

actions:
  goto_r1:
    guard: "1"
    weight: 1.0

  goto_r2:
    guard: "1"
    weight: 1.0

  goto_r3:
    guard: "1"
    weight: 1.0
"""


def create_transition_system():
    """Create a two-region transition system from YAML."""
    ts_dict = import_ts_from_file(
        StringIO(TS_YAML)
    )
    state_models = state_models_from_ts(
        ts_dict
    )
    return TSModel(state_models)


def create_branching_transition_system():
    """Create a branching TS with a multi-action accepting cycle."""
    ts_dict = import_ts_from_file(
        StringIO(BRANCHING_TS_YAML)
    )
    state_models = state_models_from_ts(
        ts_dict
    )
    return TSModel(state_models)


def test_static_planning_finds_accepting_run():
    """Build the complete planning chain and find an accepting run."""
    assert shutil.which("ltl2ba") is not None, (
        "ltl2ba must be available on PATH"
    )

    transition_system = create_transition_system()

    planner = LTLPlanner(
        transition_system,
        hard_spec="<> r2",
        soft_spec="(r2 || ! r2)",
        beta=1000,
        gamma=10,
    )

    success = planner.optimal(
        style="static"
    )

    assert success is True
    assert planner.product is not None
    assert planner.run is not None
    assert planner.planning_time is not None
    assert planner.planning_time >= 0

    assert ("r1",) in planner.run.line
    assert ("r2",) in planner.run.line

    assert planner.run.pre_plan
    assert planner.run.suf_plan

    assert planner.next_move == "goto_r2"
    assert planner.segment == "line"
    assert planner.index == 0

    assert planner.opt_log
    assert planner.opt_log[-1][1] == planner.run.pre_plan
    assert planner.opt_log[-1][2] == planner.run.suf_plan


def test_unknown_planning_style_is_rejected():
    """Reject unsupported planning modes without raising an exception."""
    transition_system = create_transition_system()

    planner = LTLPlanner(
        transition_system,
        hard_spec="<> r2",
        soft_spec="(r2 || ! r2)",
    )

    assert planner.optimal(
        style="unknown"
    ) is False
    assert planner.run is None


def test_possible_states_survive_suffix_cycle_boundaries():
    """Keep the product belief nonempty across repeated suffix cycles."""
    planner = LTLPlanner(
        create_branching_transition_system(),
        hard_spec="<> r3",
        soft_spec="(r3 || ! r3)",
    )

    assert planner.optimal(style="static") is True
    assert planner.run is not None
    assert len(planner.run.suf_plan) > 1

    for reached_state in planner.run.line[1:]:
        assert planner.update_possible_states(reached_state) is True
        planner.find_next_move()

    assert planner.segment == "loop"

    for _ in range(2):
        for reached_state in planner.run.loop[1:]:
            assert planner.update_possible_states(reached_state) is True
            planner.find_next_move()


def test_failed_task_replanning_restores_previous_planner_state():
    """Roll back task, TS initial state, plan, and execution cursor."""
    planner = LTLPlanner(
        create_transition_system(),
        hard_spec="<> r2",
        soft_spec="(r2 || ! r2)",
    )
    assert planner.optimal(style="static") is True

    planner.curr_ts_state = ("r1",)
    previous_run = (
        list(planner.run.pre_plan),
        list(planner.run.suf_plan),
    )
    previous_initial = set(
        planner.product.graph["ts"].graph["initial"]
    )
    previous_cursor = (
        planner.segment,
        planner.index,
        planner.next_move,
        planner.curr_ts_state,
    )

    assert planner.replan_task(
        hard_spec="<> r1",
        soft_spec="(r1 || ! r1)",
        initial_ts_state=("r2",),
    ) is False

    assert planner.hard_spec == "<> r2"
    assert planner.soft_spec == "(r2 || ! r2)"
    assert planner.product.graph["ts"].graph["initial"] == previous_initial
    assert (
        list(planner.run.pre_plan),
        list(planner.run.suf_plan),
    ) == previous_run
    assert (
        planner.segment,
        planner.index,
        planner.next_move,
        planner.curr_ts_state,
    ) == previous_cursor


def test_unknown_state_replanning_preserves_current_plan():
    """Reject an unknown TS state without changing the active plan."""
    planner = LTLPlanner(
        create_transition_system(),
        hard_spec="<> r2",
        soft_spec="(r2 || ! r2)",
    )
    assert planner.optimal(style="static") is True

    previous_initial = set(
        planner.product.graph["ts"].graph["initial"]
    )
    previous_next_move = planner.next_move

    assert planner.replan_from_ts_state(("unknown",)) is False
    assert planner.product.graph["ts"].graph["initial"] == previous_initial
    assert planner.next_move == previous_next_move


def test_replanning_exception_restores_previous_state(monkeypatch):
    """Restore the active planner before propagating an internal error."""
    planner = LTLPlanner(
        create_transition_system(),
        hard_spec="<> r2",
        soft_spec="(r2 || ! r2)",
    )
    assert planner.optimal(style="static") is True

    previous_run = (
        list(planner.run.pre_plan),
        list(planner.run.suf_plan),
    )
    previous_initial = set(
        planner.product.graph["ts"].graph["initial"]
    )

    def fail_buchi(*args, **kwargs):
        raise RuntimeError("injected Büchi construction failure")

    monkeypatch.setattr(
        "ltl_automaton_planner_core.ltl_tools.ltl_planner."
        "mission_to_buchi",
        fail_buchi,
    )

    with pytest.raises(RuntimeError, match="injected Büchi"):
        planner.replan_task(
            hard_spec="<> r1",
            soft_spec="(r1 || ! r1)",
            initial_ts_state=("r2",),
        )

    assert planner.hard_spec == "<> r2"
    assert planner.soft_spec == "(r2 || ! r2)"
    assert planner.product.graph["ts"].graph["initial"] == previous_initial
    assert (
        list(planner.run.pre_plan),
        list(planner.run.suf_plan),
    ) == previous_run
