"""Integration tests for the ROS-independent LTL planner."""

from copy import deepcopy
import shutil
from io import StringIO

from networkx import DiGraph
import pytest

from ltl_automaton_planner_core.boolean_formulas.parser import parse as parse_guard
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


def create_transition_system_with_isolated_r3():
    """Add an unreachable r3 self-loop to the two-region TS."""
    transition_system = create_transition_system()
    transition_system.build_full()
    transition_system.add_node(("r3",), label={"r3"})
    transition_system.add_edge(
        ("r3",),
        ("r3",),
        action="stay_r3",
        guard="1",
        weight=1.0,
    )
    return transition_system


def create_branching_transition_system():
    """Create a branching TS with a multi-action accepting cycle."""
    ts_dict = import_ts_from_file(
        StringIO(BRANCHING_TS_YAML)
    )
    state_models = state_models_from_ts(
        ts_dict
    )
    return TSModel(state_models)


@pytest.mark.parametrize("name", ["beta", "gamma"])
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), True])
def test_invalid_planning_weights_are_rejected(name, value):
    """Reject invalid objective weights before invoking an LTL translator."""
    with pytest.raises(ValueError, match=name):
        LTLPlanner(create_transition_system(), "1", "1", **{name: value})


def test_static_planning_preserves_explicit_initial_state():
    """Reuse a built TS without resetting an explicitly selected start."""
    ts = create_transition_system()
    ts.build_full()
    assert ts.set_initial(("r2",))
    planner = LTLPlanner(ts, "<> r2", "(r2 || !r2)")
    assert planner.optimal()
    assert planner.run.line[0] == ("r2",)


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


def test_unplanned_word_does_not_use_selected_run_accepting_boundary():
    """Track a reachable alternative word without borrowing the plan cursor."""
    planner = LTLPlanner(
        create_branching_transition_system(), "[]<> r1", "[] !r3", beta=1, gamma=1,
    )
    assert planner.optimal()
    for reached in (("r3",), ("r1",)):
        expected = planner.product.get_possible_states(reached)
        assert expected
        assert planner.update_possible_states(reached, enforce_accepting_boundary=False)
        assert planner.product.possible_states == expected


def test_unplanned_word_still_rejects_a_violated_hard_guard():
    """Skipping a selected boundary never creates forbidden Product edges."""
    planner = LTLPlanner(
        create_branching_transition_system(), "[] !r3", "(r1 || !r1)", gamma=1,
    )
    assert planner.optimal()
    # Product guards consume the source label: r3 invalidates the next edge.
    assert planner.update_possible_states(("r3",), enforce_accepting_boundary=False)
    assert not planner.update_possible_states(("r1",), enforce_accepting_boundary=False)


def test_history_replanning_starts_from_latest_reached_state():
    """Do not replay the source of an action that already completed."""
    planner = LTLPlanner(create_transition_system(), "<> r2", "(r2 || !r2)", gamma=3)
    assert planner.optimal()
    reached = planner.run.line[1]
    assert planner.update_possible_states(reached)
    planner.find_next_move()
    previous_run = planner.run
    previous_cursor = (planner.segment, planner.index, planner.next_move)
    previous_trace = list(planner.trace)

    assert planner.replan() is False

    assert planner.run is previous_run
    assert (planner.segment, planner.index, planner.next_move) == previous_cursor
    assert planner.trace == previous_trace


def test_history_replanning_uses_gamma_and_product_paths(monkeypatch):
    """Distinguish equal action names leading to differently weighted loops."""
    ts = DiGraph(initial={("s0",)})
    for source, target, cost, action in [
        ("s0", "a", 1, "move"), ("s0", "b", 5, "move"),
        ("a", "a", 4, "wait"), ("b", "b", 1, "wait"),
    ]:
        ts.add_edge((source,), (target,), weight=cost, action=action)
    for state in ts:
        ts.nodes[state]["label"] = set(state)
    buchi = DiGraph(type="hard_buchi", initial={"q0"}, accept={"q0"})
    buchi.add_edge("q0", "q0", guard=parse_guard("1"))
    monkeypatch.setattr(
        "ltl_automaton_planner_core.ltl_tools.ltl_planner.mission_to_buchi",
        lambda *_args: buchi,
    )
    planner = LTLPlanner(ts, "1", "1", gamma=1)
    assert planner.optimal()
    assert planner.run.suffix == [(("a",), "q0")]
    assert planner.run.totalcost == 5
    previous_actions = (planner.run.pre_plan, planner.run.suf_plan)

    planner.gamma = 10
    assert planner.replan()

    assert planner.run.suffix == [(("b",), "q0")]
    assert planner.run.totalcost == 15
    assert (planner.run.pre_plan, planner.run.suf_plan) == previous_actions


def test_new_task_discards_previous_task_history():
    """Keep historical words within the task that observed them."""
    planner = LTLPlanner(create_transition_system(), "<> r2", "(r2 || !r2)")
    assert planner.optimal()
    reached = planner.run.line[1]
    assert planner.update_possible_states(reached)
    planner.find_next_move()
    assert planner.trace

    assert planner.replan_task("[] r2", "(r2 || !r2)", initial_ts_state=reached)

    assert planner.trace == []
    assert planner.replan() is False


def test_history_replanning_keeps_execution_consistent_across_cycles():
    """Retain the current TS state and feasible belief after repeated replans."""
    planner = LTLPlanner(create_branching_transition_system(), "<> r3", "(r3 || !r3)")
    assert planner.optimal()
    for _ in range(8):
        states = planner.run.line if planner.segment == "line" else planner.run.loop
        reached = states[planner.index + 1]
        assert planner.update_possible_states(reached)
        planner.find_next_move()
        completed_sources = list(planner.trace)

        planner.replan()

        current_states = planner.run.line if planner.segment == "line" else planner.run.loop
        assert current_states[planner.index] == reached
        assert planner.trace == completed_sources
        assert planner.product.possible_states


def test_failed_task_replanning_restores_previous_planner_state():
    """Roll back task, TS initial state, plan, and execution cursor."""
    planner = LTLPlanner(
        create_transition_system(),
        hard_spec="<> r2",
        soft_spec="(r2 || ! r2)",
    )
    assert planner.optimal(style="static") is True
    assert planner.update_possible_states(planner.run.line[1]) is True

    planner.curr_ts_state = ("r1",)
    external_ts = planner.ts
    external_product = planner.product
    external_run = planner.run
    previous_run = (
        list(planner.run.pre_plan),
        list(planner.run.suf_plan),
    )
    previous_initial = set(
        planner.product.graph["ts"].graph["initial"]
    )
    previous_possible_states = deepcopy(
        planner.product.possible_states
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
    assert planner.ts is external_ts
    assert planner.product is external_product
    assert planner.run is external_run
    assert external_product.graph["ts"] is external_ts
    assert external_ts.graph["initial"] == previous_initial
    assert external_product.graph["ts"].graph["initial"] == previous_initial
    assert external_product.possible_states == previous_possible_states
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


def test_failed_ts_state_replanning_preserves_external_references():
    """Keep active objects when a new initial state is infeasible."""
    planner = LTLPlanner(
        create_transition_system_with_isolated_r3(),
        hard_spec="<> r2",
        soft_spec="(r2 || ! r2)",
    )
    assert planner.optimal(style="static") is True
    assert planner.update_possible_states(planner.run.line[1]) is True

    external_ts = planner.ts
    external_product = planner.product
    external_run = planner.run
    previous_initial = set(
        external_ts.graph["initial"]
    )
    previous_possible_states = deepcopy(
        external_product.possible_states
    )

    assert planner.replan_from_ts_state(("r3",)) is False

    assert planner.ts is external_ts
    assert planner.product is external_product
    assert planner.run is external_run
    assert external_product.graph["ts"] is external_ts
    assert external_ts.graph["initial"] == previous_initial
    assert external_product.graph["ts"].graph["initial"] == previous_initial
    assert external_product.possible_states == previous_possible_states


def test_replanning_exception_restores_previous_state(monkeypatch):
    """Restore the active planner before propagating an internal error."""
    planner = LTLPlanner(
        create_transition_system(),
        hard_spec="<> r2",
        soft_spec="(r2 || ! r2)",
    )
    assert planner.optimal(style="static") is True

    external_ts = planner.ts
    external_product = planner.product
    external_run = planner.run
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
    assert planner.ts is external_ts
    assert planner.product is external_product
    assert planner.run is external_run
    assert external_product.graph["ts"] is external_ts
    assert external_ts.graph["initial"] == previous_initial
    assert external_product.graph["ts"].graph["initial"] == previous_initial
    assert planner.product.graph["ts"].graph["initial"] == previous_initial
    assert (
        list(planner.run.pre_plan),
        list(planner.run.suf_plan),
    ) == previous_run
