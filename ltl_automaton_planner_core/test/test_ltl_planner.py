"""Integration tests for the ROS-independent LTL planner."""

import shutil
from io import StringIO

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


def create_transition_system():
    """Create a two-region transition system from YAML."""
    ts_dict = import_ts_from_file(
        StringIO(TS_YAML)
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
